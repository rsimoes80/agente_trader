"""Optional forecast collector or isolated inference engine; never routes orders."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

if __name__ == "__main__":
    if "--engine" in sys.argv:
        from aurelia_fx.forecasting.engine import engine_main

        raise SystemExit(engine_main())
    from aurelia_fx.forecasting.runner import main

    raise SystemExit(main())
