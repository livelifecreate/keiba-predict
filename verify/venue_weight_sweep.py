"""
競馬場巧者指数の配点スイープ

配点案1（+2/+1/0/-1.5）は2026-07-18のablationで悪化・却下。
本スクリプトで残り3案を一括検証する:
  A: 減点のみ   {hi:0,   mid:0,   low:0, bad:-1.5}
  B: 半減       {hi:1.0, mid:0.5, low:0, bad:-0.75}
  C: 加点のみ   {hi:1.0, mid:0.5, low:0, bad:0}

各案でCSVを出力 → bet_metrics_standard.py で9馬券種検証。
"""
import sys, subprocess
from pathlib import Path

sys.path.insert(0, '/Users/du/Documents/競馬予想システム')
sys.path.insert(0, '/Users/du/Documents/競馬予想システム/verify')

import aptitude_index

BASE = Path('/Users/du/Documents/競馬予想システム')

VARIANTS = {
    "A_negonly":  {"hi": 0.0, "mid": 0.0, "low": 0.0, "bad": -1.5},
    "B_half":     {"hi": 1.0, "mid": 0.5, "low": 0.0, "bad": -0.75},
    "C_posonly":  {"hi": 1.0, "mid": 0.5, "low": 0.0, "bad": 0.0},
}


def run_variant(name: str, weights: dict):
    import importlib
    import rerun_with_flags  # noqa

    aptitude_index.FEATURE_FLAGS['venue_aptitude'] = True
    aptitude_index.VENUE_WEIGHTS.update(weights)
    print(f"\n===== 配点案 {name}: {weights} =====", flush=True)

    # rerun_with_flags.main() を argv 差し替えで呼ぶ（フラグは上で直接設定済み）
    old_argv = sys.argv
    sys.argv = ['rerun_with_flags.py', '--label', name]
    try:
        rerun_with_flags.main()
    finally:
        sys.argv = old_argv


def main():
    for name, w in VARIANTS.items():
        run_variant(name, w)

    # 検証
    for name in VARIANTS:
        csv_path = BASE / 'data' / f'検証_条件適性_{name}.csv'
        out = subprocess.run(
            [sys.executable, str(BASE / 'verify' / 'bet_metrics_standard.py'),
             '--csv', str(csv_path), '--label', f'競馬場巧者 {name}'],
            capture_output=True, text=True)
        log = Path(f'/tmp/keiba_metrics_{name}.log')
        log.write_text(out.stdout + out.stderr)
        print(f"検証完了: {name} → {log}")


if __name__ == '__main__':
    main()
