# ==============================================================================
# The full source code of the project with DETAILED COMMENTS
# is available in the public GitHub repository:
# https://github.com/d4k3r/lazytest
# ==============================================================================
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TESTING_DIR = os.path.abspath(os.path.join(BASE_DIR, ".."))

CSV_LLM = os.path.join(
    TESTING_DIR, "generated_tests", "qwen_coder", "run_1", "metrics_fixed_coverage.csv"
)

CSV_PYNGUIN = os.path.join(
    TESTING_DIR, "generated_tests", "pynguin", "run_1", "metrics_pynguin_TheAlgorithms.csv"
)

def load_and_clean(path):
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path)
    cols = ["n_tests", "gen_time_s", "chars", "file_cov_pct", "repo_cov_pct"]
    for col in cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    df["module"] = df["source_file"].apply(lambda x: str(x).split("/")[-1])
    return df

df_llm = load_and_clean(CSV_LLM)
df_py = load_and_clean(CSV_PYNGUIN)

print("\n" + "=" * 40)
print("LLM (QWEN CODER) STATISTICS")
print("=" * 40)

total = len(df_llm)
success = (df_llm["status"] == "ok").sum()
syntax_err = (df_llm["status"] == "syntax_error").sum()
llm_err = (df_llm["status"] == "llm_error").sum()

print(f"Total files: {total}")
print(f"Success: {success} ({round(success / total * 100, 2)}%)")
print(f"Syntax Errors (Hallucinations): {syntax_err}")
print(f"LLM/Connection Errors: {llm_err}")
print(f"Avg Coverage (Success only): {round(df_llm[df_llm['status'] == 'ok']['file_cov_pct'].mean(), 2)}%")
print(f"Total Generation Time: {round(df_llm['gen_time_s'].sum() / 60, 2)} minutes")

print("\n" + "="*40)
print("LLM (QWEN CODER) STATISTICS")
print("="*40)

total = len(df_llm)
print(f"Total files: {total}")

status_counts = df_llm["status"].value_counts()
for status, count in status_counts.items():
    pct = round(count / total * 100, 2)
    print(f" - {status}: {count} ({pct}%)")

print(f"\nAvg Coverage (Success only): {round(df_llm[df_llm['status']=='ok']['file_cov_pct'].mean(), 2)}%")
print(f"Total Generation Time: {round(df_llm['gen_time_s'].sum() / 60, 2)} minutes")


if df_py is not None:
    print("\n" + "=" * 40)
    print("COMPARISON: LLM VS PYNGUIN")
    print("=" * 40)

    comparison = pd.DataFrame({
        "Metric": ["Success Rate (%)", "Avg Coverage (%)", "Avg Time (s)", "Total Tests"],
        "Qwen-Coder-30B": [
            round(success / total * 100, 2),
            round(df_llm[df_llm['status'] == 'ok']['file_cov_pct'].mean(), 2),
            round(df_llm[df_llm['status'] == 'ok']['gen_time_s'].mean(), 2),
            int(df_llm["n_tests"].sum())
        ],
        "Pynguin": [
            round((df_py["status"] == "ok").sum() / len(df_py) * 100, 2),
            round(df_py[df_py['status'] == 'ok']['file_cov_pct'].mean(), 2),
            round(df_py[df_py['status'] == 'ok']['gen_time_s'].mean(), 2),
            int(df_py["n_tests"].sum())
        ]
    })
    print(comparison.to_string(index=False))


sns.set(style="whitegrid", context="talk")
fig, axes = plt.subplots(1, 2, figsize=(16, 6))

def my_autopct(pct):
    return f'{pct:.1f}%' if pct >= 2.0 else ''


wedges, texts, autotexts = axes[0].pie(
    status_counts,
    labels=None,
    autopct=my_autopct,
    startangle=140,
    colors=sns.color_palette("viridis", len(status_counts))
)

legend_labels = [f"{idx} - {val} ({round(val / total * 100, 1)}%)" for idx, val in
                 zip(status_counts.index, status_counts.values)]

axes[0].legend(wedges, legend_labels, title="Statuses", loc="center left", bbox_to_anchor=(0.9, 0.5), fontsize=11)
axes[0].set_title("LLM Generation Statuses")

if df_py is not None:
    df_llm['Method'] = 'Qwen Coder'
    df_py['Method'] = 'Pynguin'
    combined_df = pd.concat([df_llm[df_llm['status'] == 'ok'], df_py[df_py['status'] == 'ok']])

    sns.boxplot(data=combined_df, x="Method", y="file_cov_pct", ax=axes[1], palette="Set2")
    axes[1].set_title("Code Coverage: LLM vs Pynguin")
    axes[1].set_ylabel("Coverage %")
else:
    sns.histplot(df_llm[df_llm['status'] == 'ok']['file_cov_pct'], kde=True, ax=axes[1])
    axes[1].set_title("LLM Coverage Distribution")

plt.tight_layout()
plt.show()