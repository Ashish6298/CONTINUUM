"""
Tests for Phase 1: Workspace & Source Code Evidence Extraction
==============================================================
Validates:
1. Workspace directory scanning and file classification.
2. Single-language and multi-language project analysis (Python & TypeScript/JS).
3. Symbol extraction (classes, methods, functions, interfaces, exports).
4. TODO/FIXME marker extraction with line numbers.
5. Graceful handling of malformed/syntax-error source files.
6. Deterministic output and checksums across repeated scans.
7. Canonical Evidence generation and ProjectState population.
"""

import tempfile
import unittest
from pathlib import Path

from core.enums import EvidenceType, EvidenceLevel
from core.state_models import CanonicalProjectState
from extractors.parsers.comment_parser import CommentMarkerParser
from extractors.parsers.js_ts_parser import JavaScriptTypeScriptParser
from extractors.parsers.python_parser import PythonParser
from extractors.workspace_extractor import WorkspaceEvidenceExtractor


class TestWorkspaceExtractor(unittest.TestCase):

    def test_comment_marker_extraction(self):
        source = """
        # TODO: Implement database connection
        def connect():
            pass
        # FIXME(ashish): Handle reconnect timeouts
        # NOTE: Using default port 5432
        """
        markers = CommentMarkerParser.extract_markers("db.py", source)
        self.assertEqual(len(markers), 3)
        self.assertEqual(markers[0].marker_type, "TODO")
        self.assertIn("Implement database connection", markers[0].text)
        self.assertEqual(markers[1].marker_type, "FIXME")
        self.assertIn("(ashish)", markers[1].text)
        self.assertEqual(markers[2].marker_type, "NOTE")

    def test_python_parser_ast_and_symbols(self):
        py_source = '''
        """Sample Module"""
        __all__ = ["AuthService", "verify_password"]

        import os
        from datetime import datetime, timezone

        # TODO: Add rate limiting
        def verify_password(plain: str, hashed: str) -> bool:
            """Verifies hashed password."""
            return True

        def _private_helper():
            pass

        class AuthService:
            """Main Authentication Service."""
            def __init__(self, secret: str):
                self.secret = secret

            async def login_user(self, username: str) -> dict:
                # FIXME: Token expiry check
                return {"token": "jwt123"}
        '''
        parser = PythonParser()
        result = parser.parse_source("src/auth.py", py_source)

        self.assertEqual(len(result.errors), 0)
        self.assertEqual(len(result.markers), 2)
        self.assertEqual(len(result.imports), 2)
        self.assertEqual(result.exported_symbols, ["AuthService", "verify_password"])

        # Check extracted symbols
        sym_names = [s.name for s in result.symbols]
        self.assertIn("verify_password", sym_names)
        self.assertIn("_private_helper", sym_names)
        self.assertIn("AuthService", sym_names)
        self.assertIn("AuthService.login_user", sym_names)

        # Check export status according to __all__
        verify_sym = next(s for s in result.symbols if s.name == "verify_password")
        self.assertTrue(verify_sym.exported)
        self.assertEqual(verify_sym.return_type, "bool")
        self.assertEqual(verify_sym.parameters, ["plain: str", "hashed: str"])

        private_sym = next(s for s in result.symbols if s.name == "_private_helper")
        self.assertFalse(private_sym.exported)

    def test_python_parser_malformed_syntax_resilience(self):
        malformed_py = """
        def broken_syntax(
            # Missing closing parenthesis and colon
            print "hello"
        """
        parser = PythonParser()
        result = parser.parse_source("broken.py", malformed_py)

        # Must not crash, should report structured error
        self.assertEqual(len(result.errors), 1)
        self.assertIn("SyntaxError", result.errors[0].message)
        self.assertEqual(len(result.symbols), 0)

    def test_js_ts_parser_symbols_and_interfaces(self):
        ts_source = """
        import { Request, Response } from 'express';
        import type { UserProfile } from './types';

        // TODO: Validate incoming token
        export interface AuthConfig {
            secretKey: string;
            expiresInSeconds: number;
        }

        export class TokenManager {
            private key: string;
        }

        export async function generateJwt(userId: string): Promise<string> {
            return "token";
        }

        export const validateSession = (sessionId: string): boolean => {
            // FIXME: Query Redis session store
            return true;
        };
        """
        parser = JavaScriptTypeScriptParser()
        result = parser.parse_source("src/auth.ts", ts_source)

        self.assertEqual(len(result.markers), 2)
        self.assertEqual(len(result.imports), 2)
        
        sym_names = {s.name: s for s in result.symbols}
        self.assertIn("AuthConfig", sym_names)
        self.assertEqual(sym_names["AuthConfig"].kind, "interface")
        self.assertTrue(sym_names["AuthConfig"].exported)

        self.assertIn("TokenManager", sym_names)
        self.assertEqual(sym_names["TokenManager"].kind, "class")

        self.assertIn("generateJwt", sym_names)
        self.assertEqual(sym_names["generateJwt"].kind, "function")

        self.assertIn("validateSession", sym_names)
        self.assertEqual(sym_names["validateSession"].kind, "arrow_function")

    def test_polyglot_workspace_full_extraction(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            # 1. Create Python source
            py_dir = root / "src" / "services"
            py_dir.mkdir(parents=True)
            (py_dir / "user_service.py").write_text("""
            # TODO: Add cache
            class UserService:
                def get_user(self, user_id: int) -> dict:
                    return {"id": user_id}
            """, encoding="utf-8")

            # 2. Create TypeScript source
            frontend_dir = root / "frontend"
            frontend_dir.mkdir(parents=True)
            (frontend_dir / "api.ts").write_text("""
            // FIXME: Catch network failure
            export function fetchUsers(): Promise<any> {
                return fetch('/api/users');
            }
            """, encoding="utf-8")

            # 3. Create Ignored folder (.git, node_modules)
            node_dir = root / "node_modules" / "pkg"
            node_dir.mkdir(parents=True)
            (node_dir / "index.js").write_text("console.log('ignored');", encoding="utf-8")

            # 4. Create Malformed file
            (root / "malformed.py").write_text("def oops(;", encoding="utf-8")

            # 5. Extract evidence
            extractor = WorkspaceEvidenceExtractor()
            state = CanonicalProjectState()
            ps = extractor.populate_project_state(str(root), state)

            # Assertions
            self.assertIn("Python", ps.detected_languages)
            self.assertIn("TypeScript", ps.detected_languages)
            self.assertNotIn("node_modules/pkg/index.js", ps.files)

            # Symbols check
            symbols = {s.name: s for s in ps.symbols}
            self.assertIn("UserService", symbols)
            self.assertIn("UserService.get_user", symbols)
            self.assertIn("fetchUsers", symbols)

            # Evidence records
            self.assertTrue(len(state.evidence_pool) >= 3)
            for ev in state.evidence_pool.values():
                self.assertTrue(ev.verify_integrity())
                self.assertEqual(ev.level, EvidenceLevel.LEVEL_2_CODE_AST)

            # Markers check
            marker_types = [m["marker_type"] for m in ps.todo_markers]
            self.assertIn("TODO", marker_types)
            self.assertIn("FIXME", marker_types)

    def test_deterministic_output_across_repeated_scans(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "main.py").write_text("def run(): pass", encoding="utf-8")

            extractor = WorkspaceEvidenceExtractor()
            
            ev_list_1 = extractor.extract(str(root))
            ev_list_2 = extractor.extract(str(root))

            self.assertEqual(len(ev_list_1), len(ev_list_2))
            for e1, e2 in zip(ev_list_1, ev_list_2):
                self.assertEqual(e1.summary, e2.summary)
                self.assertEqual(e1.raw_payload, e2.raw_payload)


if __name__ == "__main__":
    unittest.main()
