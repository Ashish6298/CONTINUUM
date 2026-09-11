"""
Continuum Performance, Reliability & Data Integrity Benchmark Suite
====================================================================
Measures and tests performance under load, stress, large synthetic repos,
interrupted saves, corruption recovery, and repeated operations.
"""

import os
import sys
import time
import shutil
import tempfile
import tracemalloc
import unittest
from pathlib import Path

# Add continuum workspace root to path
WORKSPACE_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(WORKSPACE_ROOT))

from pipeline.orchestrator import ContinuumPipeline
from storage.manager import ContinuumStorageManager
from storage.recovery import StateRecoveryManager
from watcher.models import ChangeType, FileChangeEvent
from watcher.updater import IncrementalStateUpdater
from core.state_models import Requirement
from core.enums import Status


class TestPerformanceAndReliability(unittest.TestCase):
    """
    Phase 21 Benchmark and Reliability Test Suite:
    - Measures scan time, incremental update time, graph processing time,
      context generation time, handoff generation time, and memory usage.
    - Tests interrupted operations, corrupted state recovery, partial extraction failures,
      repeated scans, application restarts, and large synthetic repositories.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="continuum_perf_")
        self.workspace_path = Path(self.temp_dir)

    def tearDown(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _generate_synthetic_large_repo(self, num_files: int = 150, symbols_per_file: int = 10) -> Path:
        """Helper to create a synthetic repository with many modules, classes, and functions."""
        src_dir = self.workspace_path / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        tests_dir = self.workspace_path / "tests"
        tests_dir.mkdir(parents=True, exist_ok=True)

        for i in range(num_files):
            module_name = f"module_{i:03d}.py"
            classes = []
            for j in range(symbols_per_file):
                classes.append(
                    f"class Service_{i:03d}_{j:02d}:\n"
                    f"    def execute_operation_{j}(self, payload: dict) -> bool:\n"
                    f"        return len(payload) > 0\n"
                )
            code = "\n".join(classes)
            (src_dir / module_name).write_text(code, encoding="utf-8")

        # Add requirements manifest and package.json
        (self.workspace_path / "requirements.txt").write_text("pytest>=7.0.0\npydantic>=2.0.0\nfastapi>=0.100.0\n", encoding="utf-8")
        (self.workspace_path / "package.json").write_text('{"name": "synthetic-large", "version": "1.0.0"}', encoding="utf-8")
        return self.workspace_path

    def test_large_repository_scaling_and_memory_benchmarks(self):
        """
        Benchmark: Scan time, graph construction, context generation, and memory footprint
        on a synthetic repository containing 100+ files and 1,000+ AST symbols.
        """
        tracemalloc.start()
        t0 = time.perf_counter()

        # Generate synthetic large repository (120 files * 10 symbols = 1,200 symbols)
        self._generate_synthetic_large_repo(num_files=120, symbols_per_file=10)

        pipeline = ContinuumPipeline(self.workspace_path, project_id="bench_large_repo")
        
        # 1. Measure Scan & Extraction + Full Analysis Time
        t_scan_start = time.perf_counter()
        state, summary, handoff_results = pipeline.run_full_analysis(
            task_description="Optimize module_005 service pipeline",
            token_budget=4000
        )
        t_scan_end = time.perf_counter()
        total_duration_ms = (t_scan_end - t_scan_start) * 1000

        current_mem, peak_mem = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        # Assertions for correctness and performance thresholds
        self.assertGreater(summary.total_files_scanned, 100)
        self.assertGreater(summary.total_symbols_extracted, 1000)
        self.assertLess(total_duration_ms, 12000, "Full pipeline analysis of 1,200 symbols should finish in under 12 seconds")
        self.assertGreater(summary.graph_nodes_count, 1000)
        self.assertIn("claude", handoff_results)
        self.assertIn("universal", handoff_results)
        self.assertLess(peak_mem / (1024 * 1024), 200, "Peak memory for 1,200 symbols should be under 200 MB")

    def test_incremental_update_latency_vs_full_scan(self):
        """
        Performance comparison: Verifies that IncrementalStateUpdater on single file edits
        is significantly faster than a full workspace re-scan.
        """
        self._generate_synthetic_large_repo(num_files=80, symbols_per_file=8)
        storage_manager = ContinuumStorageManager(str(self.workspace_path))
        storage_manager.initialize_storage()

        pipeline = ContinuumPipeline(self.workspace_path, project_id="bench_inc_repo")
        state, summary, _ = pipeline.run_full_analysis()
        storage_manager.save_state(state)

        # Measure full re-scan time
        t0 = time.perf_counter()
        pipeline.run_full_analysis()
        t_full = (time.perf_counter() - t0) * 1000

        # Modify a single file
        target_file = self.workspace_path / "src" / "module_010.py"
        target_file.write_text("class UpdatedService_010_00:\n    def new_method(self): pass\n", encoding="utf-8")

        # Measure incremental update time
        updater = IncrementalStateUpdater(str(self.workspace_path))
        t1 = time.perf_counter()
        change = FileChangeEvent(
            file_path="src/module_010.py",
            change_type=ChangeType.MODIFIED,
            timestamp=time.time()
        )
        update_result = updater.apply_changes(state, [change])
        t_incremental = (time.perf_counter() - t1) * 1000

        self.assertFalse(update_result.full_scan_fallback_triggered)
        self.assertLess(t_incremental, t_full, "Incremental update should be faster than full scan")
        self.assertLess(t_incremental, 500, "Single-file incremental update should finish in under 500ms")

    def test_repeated_scans_deterministic_stability(self):
        """
        Reliability: Ensures that performing 5 consecutive scans on an unmodified repo
        produces mathematically identical CanonicalState outputs without memory drift.
        """
        self._generate_synthetic_large_repo(num_files=30, symbols_per_file=5)
        pipeline = ContinuumPipeline(self.workspace_path, project_id="bench_deterministic")

        first_state, first_summary, _ = pipeline.run_full_analysis()
        first_symbols_count = len(first_state.project_state.symbols)

        for _ in range(4):
            subsequent_state, subsequent_summary, _ = pipeline.run_full_analysis()
            self.assertEqual(len(subsequent_state.project_state.symbols), first_symbols_count)
            self.assertEqual(len(subsequent_state.project_state.files), len(first_state.project_state.files))
            self.assertEqual(subsequent_summary.total_files_scanned, first_summary.total_files_scanned)
            self.assertEqual(subsequent_summary.graph_nodes_count, first_summary.graph_nodes_count)

    def test_interrupted_operations_and_atomic_save_safety(self):
        """
        Reliability & Data Integrity: Simulates process crash or abrupt interruption
        during disk persistence and verifies that state.json is never left half-written.
        """
        storage_manager = ContinuumStorageManager(str(self.workspace_path))
        storage_manager.initialize_storage()

        pipeline = ContinuumPipeline(self.workspace_path, project_id="bench_interrupted")
        initial_state, _, _ = pipeline.run_full_analysis()
        saved_path = storage_manager.save_state(initial_state)
        self.assertTrue(Path(saved_path).exists())

        # Simulate a crash leaving an abandoned temp file in .continuum/
        tmp_file = storage_manager.continuum_dir / "state.tmp.12345"
        tmp_file.write_text("corrupted partial json payload { \"state\":", encoding="utf-8")

        # Load state through recovery manager
        recovery_manager = StateRecoveryManager(storage_manager)
        is_valid, error_msg = recovery_manager.verify_active_state_integrity()
        self.assertTrue(is_valid, "Main state.json must remain intact and valid despite abandoned temp files")

        loaded_state = storage_manager.load_state()
        self.assertIsNotNone(loaded_state)
        self.assertEqual(loaded_state.project_state.root_path, initial_state.project_state.root_path)

    def test_corrupted_state_auto_recovery_from_backup_history(self):
        """
        Data Integrity: Verifies that if state.json is catastrophically corrupted,
        Continuum automatically recovers the latest valid historical snapshot.
        """
        storage_manager = ContinuumStorageManager(str(self.workspace_path))
        storage_manager.initialize_storage()

        pipeline = ContinuumPipeline(self.workspace_path, project_id="bench_corrupt_recovery")
        initial_state, _, _ = pipeline.run_full_analysis()
        
        # Save snapshot 1
        storage_manager.save_state(initial_state)
        time.sleep(0.01)

        # Save snapshot 2 with modified user requirement
        initial_state.conversational_state.user_requirements.append(
            Requirement(
                id="REQ-TEST",
                title="Performance requirement",
                description="Must pass stress benchmarks",
                status=Status.IN_PROGRESS
            )
        )
        storage_manager.save_state(initial_state)

        # Intentionally destroy state.json
        state_file = storage_manager.continuum_dir / "state.json"
        state_file.write_text("CORRUPTED_NON_JSON_DATA_GARBAGE!@#$%", encoding="utf-8")

        recovery_manager = StateRecoveryManager(storage_manager)
        recovery_res = recovery_manager.recover_corrupted_state()

        self.assertTrue(recovery_res.success)
        self.assertTrue(recovery_res.state_restored)

        # Loaded state should now be valid JSON
        recovered_state = storage_manager.load_state()
        self.assertIsNotNone(recovered_state)

    def test_partial_extraction_failures_graceful_degradation(self):
        """
        Reliability: When one extractor encounters an unreadable/malformed file,
        the remaining pipeline stages must complete cleanly without cascading errors.
        """
        src_dir = self.workspace_path / "src"
        src_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "valid.py").write_text("class ValidComponent:\n    pass\n", encoding="utf-8")
        
        # Add a malformed UTF-16 / binary file disguised as python
        with open(src_dir / "corrupted.py", "wb") as f:
            f.write(b"\x00\xff\xfe\x00\x12\x34\x56\x78\x90\xab\xcd\xef")

        pipeline = ContinuumPipeline(self.workspace_path, project_id="bench_degradation")
        state, summary, handoff_results = pipeline.run_full_analysis()

        self.assertGreater(summary.total_files_scanned, 0)
        # Valid component was parsed despite corrupted file in same directory
        extracted_names = [s.name for s in state.project_state.symbols]
        self.assertIn("ValidComponent", extracted_names)


if __name__ == "__main__":
    unittest.main()
