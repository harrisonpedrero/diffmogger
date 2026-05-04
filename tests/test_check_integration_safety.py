from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "check_integration_safety.py"


def load_checker():
    spec = importlib.util.spec_from_file_location("check_integration_safety", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class IntegrationSafetyCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_checker()

    def write_text(self, root: Path, rel_path: str, text: str) -> None:
        path = root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def seed_minimal_safe_tree(self, root: Path) -> None:
        self.write_text(
            root,
            "services/agentic-notifier/agentic_notifier/config.py",
            '\n'.join(
                [
                    'notifier_api_host: str = "127.0.0.1"',
                    'webhook_host: str = "127.0.0.1"',
                    "dry_run: bool = True",
                    'dry_run=_truthy(os.getenv("DRY_RUN", "true"))',
                ]
            ),
        )
        self.write_text(
            root,
            "services/agentic-notifier/.env.example",
            '\n'.join(
                [
                    "TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                    "TWILIO_FROM=+15555555555",
                    "HUMAN_TO=+15555555555",
                    "NOTIFIER_API_HOST=127.0.0.1",
                    "WEBHOOK_HOST=127.0.0.1",
                    "WEBHOOK_PUBLIC_BASE_URL=https://example.ngrok-free.app",
                    "DRY_RUN=true",
                ]
            ),
        )
        self.write_text(
            root,
            "services/agentic-notifier/agentic_notifier/api_app.py",
            'LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}\n'
            "LOCAL_NOTIFY_API_TOKEN is required when API host is not loopback\n",
        )
        self.write_text(
            root,
            "services/agentic-notifier/scripts/send_test_notification.py",
            '"dry_run": not args.real_send\n',
        )
        self.write_text(
            root,
            "services/agentic-notifier/README.md",
            "The example config starts with `DRY_RUN=true`\n"
            "Do not expose `http://127.0.0.1:8765/api/notify` through ngrok.\n",
        )
        self.write_text(root, "scripts/scaffold_project_docs.py", 'return "file_only"\n')
        self.write_text(
            root,
            "docs/HUMAN_BRIDGE_SETUP.md",
            "No SMS, WhatsApp, Twilio, webhook, ngrok, notifier API, or messaging credentials are used in this mode.\n",
        )
        self.write_text(
            root,
            "services/agentic-dashboard/agentic_dashboard/app.py",
            "File-only handoff remains available if notifier setup is incomplete.\n"
            "allow_remotes: bool = False\n",
        )
        self.write_text(root, "README.md", "# Safe placeholder docs\n")

    def test_current_repo_passes_integration_safety(self) -> None:
        problems = self.module.check_integration_safety(ROOT)
        self.assertEqual([], problems)

    def test_detects_realistic_secret_and_non_placeholder_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.seed_minimal_safe_tree(target)
            self.write_text(
                target,
                "docs/HUMAN_BRIDGE.md",
                "Live bad values: AC" "0123456789abcdef0123456789abcdef and https://team.ngrok-free.app\n",
            )

            problems = self.module.check_integration_safety(target)

            details = "\n".join(problem.detail for problem in problems)
            self.assertIn("concrete-looking Twilio Account SID", details)
            self.assertIn("non-placeholder ngrok URL", details)

    def test_detects_missing_dry_run_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            self.seed_minimal_safe_tree(target)
            config = target / "services/agentic-notifier/agentic_notifier/config.py"
            config.write_text(
                config.read_text(encoding="utf-8").replace("dry_run: bool = True", "dry_run: bool = False"),
                encoding="utf-8",
            )

            problems = self.module.check_integration_safety(target)

            self.assertTrue(
                any(problem.detail == "notifier settings must default to dry-run" for problem in problems)
            )


if __name__ == "__main__":
    unittest.main()
