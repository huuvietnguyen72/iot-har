from .artifact import write_json
from .config import LABELS

UCI_TITLE = "UCI HAR — baseline bốn hoạt động (Random Forest)"
UCI_NOTES = ["Nguồn: UCI HAR (Reyes-Ortiz et al., 2013), DOI 10.24432/C54S4K, CC BY 4.0.", "",
             "Kết quả trên smartphone dataset; chưa chứng minh độ chính xác MPU6050 đeo trên người."]
UCI_CV_METHOD = "cross-validation theo người (GroupKFold) trên tập train"


def write_report(run_dir, results):
    write_json(run_dir / "report.json", results)
    lines = [f"# {results.get('title', UCI_TITLE)}", "", *results.get("notes", UCI_NOTES), "",
             "## Chọn cấu hình", "",
             f"Phương pháp: {results.get('cv_method', UCI_CV_METHOD)}; "
             "chọn bằng macro-F1 trung bình, không dùng test.", "",
             f"**Cấu hình chọn:** `{results['selected_config']}` — CV macro-F1 "
             f"{results['selected_cv_mean_macro_f1']:.6f} ± {results['selected_cv_std_macro_f1']:.6f}.", "",
             "| n_estimators | max_features | min_samples_leaf | max_depth | class_weight | CV macro-F1 |",
             "| ---: | --- | ---: | ---: | --- | ---: |"]
    for item in sorted(results["cv_selection"], key=lambda r: -r["mean_macro_f1"]):
        c = item["config"]
        lines.append(f"| {c['n_estimators']} | {c['max_features']} | {c['min_samples_leaf']} | "
                     f"{c['max_depth']} | {c['class_weight']} | "
                     f"{item['mean_macro_f1']:.6f} ± {item['std_macro_f1']:.6f} |")
    if results.get("oob_score") is not None:
        lines += ["", f"OOB trên tập train (ước lượng, không thay test): {results['oob_score']:.6f}"]
    lines += ["", f"## {results.get('test_heading', 'Official held-out test')}", "",
              "| Model | Accuracy | Macro-F1 |", "| --- | ---: | ---: |"]
    for name, data in results["test"].items():
        lines.append(f"| {name} | {data['accuracy']:.6f} | {data['macro_f1']:.6f} |")
    comparison = results.get("comparison")
    if comparison:
        lines.append(f"| compare ({comparison['run_dir']}) | {comparison['accuracy']:.6f} | "
                     f"{comparison['macro_f1']:.6f} |")
    lines += ["", "## Selected model per-class metrics", "",
              "| Label | Precision | Recall | F1 | Support |",
              "| --- | ---: | ---: | ---: | ---: |"]
    for label in LABELS:
        row = results["test"]["selected"]["per_class"][label]
        lines.append(f"| {label} | {row['precision']:.6f} | {row['recall']:.6f} | "
                     f"{row['f1-score']:.6f} | {int(row['support'])} |")
    lines += ["", "## Confusion matrix (hàng thật, cột dự đoán)", "",
              "| True / predicted | walk | sit | stand | lie |",
              "| --- | ---: | ---: | ---: | ---: |"]
    for label, row in zip(LABELS, results["test"]["selected"]["confusion_matrix"]):
        lines.append("| " + label + " | " + " | ".join(map(str, row)) + " |")
    if results.get("test_groups"):
        lines += ["", "## Độ chính xác theo từng phiên test", "",
                  "| Phiên | Nhãn | Cửa sổ | Accuracy |", "| --- | --- | ---: | ---: |"]
        for row in results["test_groups"]:
            lines.append(f"| {row['group']} | {', '.join(row['labels'])} | {row['windows']} | "
                         f"{row['accuracy']:.6f} |")
    lines += ["", f"Macro-F1 target >=0.85: **{results['quality_goal_met']}**.",
              f"Better than Dummy on test: **{results['beats_dummy']}**.", "",
              "## Warnings", "", *results["warnings"], ""]
    with (run_dir / "report.md").open("x", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
