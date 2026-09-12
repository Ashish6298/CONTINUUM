"""
Project Continuum - Configuration and Manifest Parsers
======================================================
Parsers for package.json, pyproject.toml, Cargo.toml, go.mod,
pubspec.yaml, Dockerfile, docker-compose.yml, and environment templates.
"""

import json
import re
from typing import Any, Dict, List, Optional

from core.state_models import ManifestInfo
from extractors.config.secret_sanitizer import SecretSanitizer

try:
    import tomllib  # Python 3.11+ standard library
except ImportError:
    try:
        import tomli as tomllib  # Python 3.10 with tomli
    except ImportError:
        tomllib = None  # Fallback handled via regex


class ManifestParser:
    """
    Parses various software package manifests and project configuration files.
    """

    @staticmethod
    def parse_package_json(file_path: str, content: str) -> ManifestInfo:
        try:
            data = json.loads(content)
        except Exception:
            return ManifestInfo(manifest_type="package.json", file_path=file_path)

        dependencies = {str(k): str(v) for k, v in data.get("dependencies", {}).items()}
        dev_dependencies = {str(k): str(v) for k, v in data.get("devDependencies", {}).items()}
        scripts = {str(k): str(v) for k, v in data.get("scripts", {}).items()}

        return ManifestInfo(
            manifest_type="package.json",
            file_path=file_path,
            project_name=data.get("name"),
            version=data.get("version"),
            dependencies=SecretSanitizer.sanitize_dict(dependencies),
            dev_dependencies=SecretSanitizer.sanitize_dict(dev_dependencies),
            scripts=scripts
        )

    @staticmethod
    def parse_pyproject_toml(file_path: str, content: str) -> ManifestInfo:
        project_name = None
        version = None
        dependencies: Dict[str, str] = {}
        dev_dependencies: Dict[str, str] = {}
        scripts: Dict[str, str] = {}

        if tomllib:
            try:
                data = tomllib.loads(content)
                proj = data.get("project", {})
                project_name = proj.get("name")
                version = proj.get("version")

                # Project dependencies
                for dep in proj.get("dependencies", []):
                    parts = re.split(r"[><=~^! ]+", dep, maxsplit=1)
                    name = parts[0].strip()
                    ver = dep[len(name):].strip() if len(parts) > 1 else "*"
                    dependencies[name] = ver or "*"

                # Optional/dev dependencies
                for group, deps in proj.get("optional-dependencies", {}).items():
                    for dep in deps:
                        parts = re.split(r"[><=~^! ]+", dep, maxsplit=1)
                        name = parts[0].strip()
                        ver = dep[len(name):].strip() if len(parts) > 1 else "*"
                        dev_dependencies[f"{group}:{name}"] = ver or "*"

                # Scripts
                scripts = {str(k): str(v) for k, v in proj.get("scripts", {}).items()}

                # Poetry fallback if present
                poetry = data.get("tool", {}).get("poetry", {})
                if poetry:
                    project_name = project_name or poetry.get("name")
                    version = version or poetry.get("version")
                    for k, v in poetry.get("dependencies", {}).items():
                        if k != "python":
                            dependencies[k] = str(v)
                    for k, v in poetry.get("group", {}).get("dev", {}).get("dependencies", {}).items():
                        dev_dependencies[k] = str(v)

            except Exception:
                pass
        else:
            # Pure Python fallback parser for Python 3.10 without tomli
            name_match = re.search(r'name\s*=\s*["\']([^"\']+)["\']', content)
            if name_match:
                project_name = name_match.group(1)
            ver_match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
            if ver_match:
                version = ver_match.group(1)
            deps_match = re.search(r'dependencies\s*=\s*\[(.*?)\]', content, re.DOTALL)
            if deps_match:
                for dep in re.findall(r'["\']([^"\']+)["\']', deps_match.group(1)):
                    parts = re.split(r"[><=~^! ]+", dep, maxsplit=1)
                    name = parts[0].strip()
                    ver = dep[len(name):].strip() if len(parts) > 1 else "*"
                    dependencies[name] = ver or "*"

        return ManifestInfo(
            manifest_type="pyproject.toml",
            file_path=file_path,
            project_name=project_name,
            version=version,
            dependencies=dependencies,
            dev_dependencies=dev_dependencies,
            scripts=scripts
        )

    @staticmethod
    def parse_cargo_toml(file_path: str, content: str) -> ManifestInfo:
        project_name = None
        version = None
        dependencies: Dict[str, str] = {}
        dev_dependencies: Dict[str, str] = {}

        if tomllib:
            try:
                data = tomllib.loads(content)
                pkg = data.get("package", {})
                project_name = pkg.get("name")
                version = pkg.get("version")

                for k, v in data.get("dependencies", {}).items():
                    dependencies[k] = str(v.get("version", "*")) if isinstance(v, dict) else str(v)

                for k, v in data.get("dev-dependencies", {}).items():
                    dev_dependencies[k] = str(v.get("version", "*")) if isinstance(v, dict) else str(v)
            except Exception:
                pass
        else:
            # Pure Python fallback parser for Python 3.10 without tomli
            name_match = re.search(r'name\s*=\s*["\']([^"\']+)["\']', content)
            if name_match:
                project_name = name_match.group(1)
            ver_match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
            if ver_match:
                version = ver_match.group(1)
            in_deps = False
            for line in content.splitlines():
                stripped = line.strip()
                if stripped.startswith("["):
                    in_deps = (stripped == "[dependencies]")
                    continue
                if in_deps and "=" in stripped:
                    k, v = stripped.split("=", 1)
                    k = k.strip()
                    v_match = re.search(r'["\']([^"\']+)["\']', v)
                    dependencies[k] = v_match.group(1) if v_match else "*"

        return ManifestInfo(
            manifest_type="Cargo.toml",
            file_path=file_path,
            project_name=project_name,
            version=version,
            dependencies=dependencies,
            dev_dependencies=dev_dependencies,
            scripts={}
        )

    @staticmethod
    def parse_go_mod(file_path: str, content: str) -> ManifestInfo:
        module_name = None
        go_version = None
        dependencies: Dict[str, str] = {}

        lines = content.splitlines()
        for line in lines:
            line = line.strip()
            if line.startswith("module "):
                module_name = line.replace("module ", "").strip()
            elif line.startswith("go "):
                go_version = line.replace("go ", "").strip()
            elif not line.startswith("//") and not line.startswith("require") and not line.startswith(")") and not line.startswith("("):
                parts = line.split()
                if len(parts) >= 2:
                    dependencies[parts[0]] = parts[1]

        scripts = {"go_version": go_version} if go_version else {}

        return ManifestInfo(
            manifest_type="go.mod",
            file_path=file_path,
            project_name=module_name,
            version=go_version,
            dependencies=dependencies,
            dev_dependencies={},
            scripts=scripts
        )

    @staticmethod
    def parse_pubspec_yaml(file_path: str, content: str) -> ManifestInfo:
        project_name = None
        version = None
        dependencies: Dict[str, str] = {}
        dev_dependencies: Dict[str, str] = {}

        current_section = None
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            if not line.startswith(" ") and ":" in stripped:
                key, val = stripped.split(":", 1)
                key = key.strip()
                val = val.strip()
                if key == "name":
                    project_name = val
                elif key == "version":
                    version = val
                elif key in {"dependencies", "dev_dependencies"}:
                    current_section = key
                else:
                    current_section = None
            elif current_section and line.startswith("  ") and ":" in stripped:
                key, val = stripped.split(":", 1)
                k = key.strip()
                v = val.strip() or "*"
                if current_section == "dependencies" and k != "flutter":
                    dependencies[k] = v
                elif current_section == "dev_dependencies":
                    dev_dependencies[k] = v

        return ManifestInfo(
            manifest_type="pubspec.yaml",
            file_path=file_path,
            project_name=project_name,
            version=version,
            dependencies=dependencies,
            dev_dependencies=dev_dependencies,
            scripts={}
        )

    @staticmethod
    def parse_dockerfile(file_path: str, content: str) -> Dict[str, Any]:
        base_images = []
        exposed_ports = []
        entrypoints = []
        cmd = None

        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("FROM "):
                base_images.append(stripped.replace("FROM ", "").strip())
            elif stripped.startswith("EXPOSE "):
                ports = stripped.replace("EXPOSE ", "").split()
                exposed_ports.extend(ports)
            elif stripped.startswith("ENTRYPOINT "):
                entrypoints.append(stripped.replace("ENTRYPOINT ", "").strip())
            elif stripped.startswith("CMD "):
                cmd = stripped.replace("CMD ", "").strip()

        return {
            "file_path": file_path,
            "base_images": base_images,
            "exposed_ports": exposed_ports,
            "entrypoint": entrypoints[0] if entrypoints else None,
            "cmd": cmd
        }

    @staticmethod
    def parse_env_template(file_path: str, content: str) -> Dict[str, Any]:
        """Extracts expected environment variable keys while redacting all values."""
        variables: List[str] = []
        for line in content.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key, _ = stripped.split("=", 1)
                variables.append(key.strip())

        return {
            "file_path": file_path,
            "variable_keys": variables,
            "sanitized": True
        }
