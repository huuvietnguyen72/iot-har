import argparse
from pathlib import Path
import sys
import time

from .collector_csv import load_collector_windows
from .dataset import load_split, prepare_dataset
from .demo_server import run_demo
from .fake_esp32 import FakeEsp32
from .inference import benchmark, predict_csv
from .live_terminal import run_live
from .sources import parse_endpoint
from .train import train_baseline
from .train_own import train_own


def _port(text):
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid port: {text!r}") from None
    if not 0 <= value <= 65535:
        raise argparse.ArgumentTypeError("port must be between 0 and 65535")
    return value


def _positive_int(text):
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid integer: {text!r}") from None
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def _parser():
    parser = argparse.ArgumentParser(prog="har", description="MPU6050 HAR (UCI baseline, own sessions, live demo)")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare", help="download and verify the UCI HAR dataset")
    prepare.add_argument("--data-dir", required=True)
    train = sub.add_parser("train", help="train and evaluate the four-activity baseline")
    train.add_argument("--data-dir", required=True)
    train.add_argument("--run-dir", required=True)
    own = sub.add_parser("train-own", help="train and evaluate on labelled MPU6050 sessions")
    own.add_argument("--train-dir", required=True)
    own.add_argument("--test-dir", required=True)
    own.add_argument("--run-dir", required=True)
    own.add_argument("--compare-run", help="existing run to evaluate on the same test sessions")
    predict = sub.add_parser("predict-csv", help="replay a collector CSV through a saved model")
    predict.add_argument("--run-dir", required=True)
    predict.add_argument("--csv", required=True)
    predict.add_argument("--output", required=True)
    bench = sub.add_parser("benchmark", help="measure feature extraction and predict latency")
    bench.add_argument("--run-dir", required=True)
    bench.add_argument("--csv", required=True)
    bench.add_argument("--output", required=True)
    esp_help = "ESP32 IP:port, e.g. 192.168.1.2:8765 (use the IP address; a host name can make stopping slower)"
    demo = sub.add_parser("demo", help="web dashboard: live ESP32 or replay recorded sessions")
    demo.add_argument("--run-dir", required=True)
    demo.add_argument("--esp", required=True, help=esp_help)
    demo.add_argument("--data-dir", required=True, help="folder with train/ and/or test/ sessions")
    demo.add_argument("--host", default="0.0.0.0")
    demo.add_argument("--port", type=_port, default=8080)
    live = sub.add_parser("live", help="print live predictions from the ESP32")
    live.add_argument("--run-dir", required=True)
    live.add_argument("--esp", required=True, help=esp_help)
    live.add_argument("--max-predictions", type=_positive_int, help=argparse.SUPPRESS)
    fake = sub.add_parser("fake-esp32", help="serve a collector CSV as a fake ESP32 TCP stream")
    fake.add_argument("--csv", required=True)
    fake.add_argument("--host", default="127.0.0.1")
    fake.add_argument("--port", type=_port, default=8765)
    fake.add_argument("--speed", type=float, default=1.0)
    return parser


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    args = _parser().parse_args(argv)
    try:
        if args.command == "prepare":
            manifest = prepare_dataset(Path(args.data_dir))
            print(f"dataset_root={manifest['dataset_root']} sha256={manifest['archive_sha256']}")
        elif args.command == "train":
            manifest = prepare_dataset(Path(args.data_dir))
            root = Path(args.data_dir) / manifest["dataset_root"]
            result = train_baseline(load_split(root, "train"), load_split(root, "test"),
                                    manifest, Path(args.run_dir))
            print(f"selected_config={result['selected_config']} test_macro_f1="
                  f"{result['test']['selected']['macro_f1']:.4f} goal_met={result['quality_goal_met']}")
        elif args.command == "train-own":
            result = train_own(Path(args.train_dir), Path(args.test_dir), Path(args.run_dir),
                               compare_run=Path(args.compare_run) if args.compare_run else None)
            print(f"selected_config={result['selected_config']} test_macro_f1="
                  f"{result['test']['selected']['macro_f1']:.4f} goal_met={result['quality_goal_met']}")
        elif args.command == "predict-csv":
            predict_csv(Path(args.run_dir), Path(args.csv), Path(args.output))
            print(f"wrote {args.output}")
        elif args.command == "benchmark":
            loaded = load_collector_windows(Path(args.csv))
            result = benchmark(Path(args.run_dir), loaded.windows, output_path=Path(args.output))
            print(f"median={result['median_s']:.6f}s p95={result['p95_s']:.6f}s "
                  f"criterion={result['criterion_p95_under_1_28']}")
        elif args.command == "demo":
            return run_demo(Path(args.run_dir), args.esp, Path(args.data_dir), args.host, args.port)
        elif args.command == "live":
            host, port = parse_endpoint(args.esp)
            return run_live(Path(args.run_dir), host, port, max_predictions=args.max_predictions)
        elif args.command == "fake-esp32":
            fake = FakeEsp32(Path(args.csv), host=args.host, port=args.port, speed=args.speed).start()
            try:
                print(f"fake-esp32: {fake.host}:{fake.port} phát {args.csv} (Ctrl+C để dừng)", flush=True)
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
            finally:
                fake.stop()
        return 0
    except KeyboardInterrupt:
        return 130
    except (ValueError, OSError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
