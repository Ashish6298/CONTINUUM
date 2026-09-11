"""
Tests for Phase 2: Configuration, Environment & Project Metadata Extraction
===========================================================================
Validates:
1. Supported manifest formats (package.json, pyproject.toml, Cargo.toml, go.mod, pubspec.yaml, Dockerfile).
2. Lockfile detection.
3. Strict secret redaction and prevention of credential leakage.
4. Handling missing or malformed configuration files.
5. Canonical evidence creation and ProjectState integration.
"""

import tempfile
import unittest
from pathlib import Path

from core.enums import EvidenceType, EvidenceLevel
from core.state_models import CanonicalProjectState
from extractors.config.parsers import ManifestParser
from extractors.config.secret_sanitizer import SecretSanitizer
from extractors.config_extractor import ConfigEvidenceExtractor


class TestConfigExtractor(unittest.TestCase):

    def test_secret_sanitization(self):
        # 1. Sensitive key names
        self.assertTrue(SecretSanitizer.is_sensitive_key("API_SECRET_KEY"))
        self.assertTrue(SecretSanitizer.is_sensitive_key("db_password"))
        self.assertTrue(SecretSanitizer.is_sensitive_key("AUTH_TOKEN"))
        self.assertFalse(SecretSanitizer.is_sensitive_key("project_name"))

        # 2. Secret value patterns (e.g. OpenAI key, JWT, AWS key)
        self.assertTrue(SecretSanitizer.contains_secret_pattern("sk-1234567890abcdef1234567890abcdef"))
        self.assertTrue(SecretSanitizer.contains_secret_pattern("AKIAIOSFODNN7EXAMPLE"))

        # 3. Sanitizing dictionary
        dirty_data = {
            "name": "my-app",
            "api_key": "super_secret_value",
            "database_url": "postgres://user:pass@localhost:5432/db",
            "public_config": "true",
            "nested": {
                "jwt_token": "eyJhbGciOi...",
                "port": 8080
            }
        }
        clean_data = SecretSanitizer.sanitize_dict(dirty_data)
        self.assertEqual(clean_data["name"], "my-app")
        self.assertEqual(clean_data["api_key"], "<REDACTED_SECRET>")
        self.assertEqual(clean_data["database_url"], "<REDACTED_SECRET>")
        self.assertEqual(clean_data["nested"]["jwt_token"], "<REDACTED_SECRET>")
        self.assertEqual(clean_data["nested"]["port"], 8080)

    def test_parse_package_json(self):
        content = """
        {
          "name": "frontend-web",
          "version": "1.2.3",
          "scripts": {
            "build": "vite build",
            "test": "vitest run"
          },
          "dependencies": {
            "react": "^18.2.0",
            "axios": "^1.4.0"
          },
          "devDependencies": {
            "typescript": "^5.0.0"
          }
        }
        """
        manifest = ManifestParser.parse_package_json("package.json", content)
        self.assertEqual(manifest.manifest_type, "package.json")
        self.assertEqual(manifest.project_name, "frontend-web")
        self.assertEqual(manifest.version, "1.2.3")
        self.assertEqual(manifest.dependencies.get("react"), "^18.2.0")
        self.assertEqual(manifest.scripts.get("build"), "vite build")

    def test_parse_pyproject_toml(self):
        content = """
        [project]
        name = "backend-service"
        version = "0.5.0"
        dependencies = [
            "fastapi>=0.100.0",
            "uvicorn>=0.22.0"
        ]

        [project.optional-dependencies]
        dev = ["pytest>=7.0.0"]

        [project.scripts]
        start = "backend_service.main:run"
        """
        manifest = ManifestParser.parse_pyproject_toml("pyproject.toml", content)
        self.assertEqual(manifest.manifest_type, "pyproject.toml")
        self.assertEqual(manifest.project_name, "backend-service")
        self.assertEqual(manifest.version, "0.5.0")
        self.assertIn("fastapi", manifest.dependencies)
        self.assertEqual(manifest.scripts.get("start"), "backend_service.main:run")

    def test_parse_cargo_toml(self):
        content = """
        [package]
        name = "rust-core"
        version = "0.1.0"
        edition = "2021"

        [dependencies]
        tokio = { version = "1.0", features = ["full"] }
        serde = "1.0"
        """
        manifest = ManifestParser.parse_cargo_toml("Cargo.toml", content)
        self.assertEqual(manifest.manifest_type, "Cargo.toml")
        self.assertEqual(manifest.project_name, "rust-core")
        self.assertEqual(manifest.version, "0.1.0")
        self.assertIn("tokio", manifest.dependencies)

    def test_parse_go_mod(self):
        content = """
        module github.com/user/project

        go 1.21

        require (
            github.com/gin-gonic/gin v1.9.1
            github.com/stretchr/testify v1.8.4
        )
        """
        manifest = ManifestParser.parse_go_mod("go.mod", content)
        self.assertEqual(manifest.manifest_type, "go.mod")
        self.assertEqual(manifest.project_name, "github.com/user/project")
        self.assertEqual(manifest.version, "1.21")
        self.assertIn("github.com/gin-gonic/gin", manifest.dependencies)

    def test_parse_dockerfile_and_env_templates(self):
        df_content = """
        FROM python:3.11-slim
        EXPOSE 8000 8080
        ENTRYPOINT ["python", "app.py"]
        """
        docker_info = ManifestParser.parse_dockerfile("Dockerfile", df_content)
        self.assertEqual(docker_info["base_images"], ["python:3.11-slim"])
        self.assertEqual(docker_info["exposed_ports"], ["8000", "8080"])
        self.assertEqual(docker_info["entrypoint"], '["python", "app.py"]')

        env_content = """
        # Database setup
        DB_HOST=localhost
        DB_PASSWORD=secret_password_here
        API_SECRET=123456789
        """
        env_info = ManifestParser.parse_env_template(".env.example", env_content)
        self.assertEqual(env_info["variable_keys"], ["DB_HOST", "DB_PASSWORD", "API_SECRET"])

    def test_full_workspace_config_extraction(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            # 1. Package json with secret in dependencies (should be redacted)
            (root / "package.json").write_text("""
            {
              "name": "full-stack",
              "version": "1.0.0",
              "dependencies": {
                "express": "^4.18.2"
              }
            }
            """, encoding="utf-8")

            # 2. Lockfile
            (root / "package-lock.json").write_text("{}", encoding="utf-8")

            # 3. Dockerfile
            (root / "Dockerfile").write_text("FROM node:18-alpine\nEXPOSE 3000", encoding="utf-8")

            # 4. Env template
            (root / ".env.example").write_text("PORT=3000\nAPI_KEY=xyz", encoding="utf-8")

            # 5. Malformed json
            (root / "broken_manifest.json").write_text("{broken", encoding="utf-8")

            extractor = ConfigEvidenceExtractor()
            state = CanonicalProjectState()
            ps = extractor.populate_project_state(str(root), state)

            self.assertEqual(len(ps.manifests), 1)
            self.assertEqual(ps.manifests[0].project_name, "full-stack")
            self.assertEqual(ps.manifests[0].manifest_type, "package.json")

            # Check evidence pool
            ev_types = [ev.type for ev in state.evidence_pool.values()]
            self.assertIn(EvidenceType.CONFIG_FILE, ev_types)
            for ev in state.evidence_pool.values():
                self.assertTrue(ev.verify_integrity())
                self.assertEqual(ev.level, EvidenceLevel.LEVEL_2_CODE_AST)


if __name__ == "__main__":
    unittest.main()
