import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CSV_PATH = (
    PROJECT_ROOT
    / "testing"
    / "generated_tests"
    / "pynguin"
    / "run_1"
    / "metrics_pynguin_TheAlgorithms.csv"
)

pd.set_option("display.max_colwidth", None)
pd.set_option("display.max_rows", None)
pd.set_option("display.width", None)

# Чтение и очистка данных
df = pd.read_csv(CSV_PATH)
df["n_tests"] = pd.to_numeric(df["n_tests"], errors="coerce").fillna(0)
df["gen_time_s"] = pd.to_numeric(df["gen_time_s"], errors="coerce").fillna(0)
df["chars"] = pd.to_numeric(df["chars"], errors="coerce").fillna(0)
df["file_cov_pct"] = pd.to_numeric(df["file_cov_pct"], errors="coerce").fillna(0)
df["repo_cov_pct"] = pd.to_numeric(df["repo_cov_pct"], errors="coerce").fillna(0)

# Извлекаем имя модуля для красоты
df["module"] = df["source_file"].apply(lambda x: str(x).split("repos_for_testing\\")[-1])

print("\n" + "="*40)
print("BASIC STATISTICS")
print("="*40)

total_files = len(df)
success = (df["status"] == "ok").sum()
no_tests = (df["status"] == "no_tests").sum()
failures = total_files - success - no_tests

print(f"Total files analysed: {total_files}")
print(f"Successful generations: {success}")
print(f"No tests generated: {no_tests}")
print(f"Failures (errors, timeouts): {failures}")
print(f"Success rate: {round(success / total_files * 100, 2)}%")

print("\n" + "="*40)
print("STATUS DISTRIBUTION")
print("="*40)
print(df["status"].value_counts())

print("\n" + "="*40)
print("COVERAGE & TEST METRICS")
print("="*40)

generated = df[df["status"] == "ok"]

if not generated.empty:
    avg_tests = generated["n_tests"].mean()
    avg_time = generated["gen_time_s"].mean()
    avg_file_cov = generated["file_cov_pct"].mean()

    print(f"Average tests per file (success only): {round(avg_tests, 2)}")
    print(f"Average generation time (success only): {round(avg_time, 2)} s")
    print(f"Average File Coverage (success only): {round(avg_file_cov, 2)}%")
else:
    print("No successful generations to analyse.")

print(f"Average File Coverage (all files, incl. failed): {round(df['file_cov_pct'].mean(), 2)}%")

print("\n--- Repository Level Coverage ---")
# Так как repo_cov_pct дублируется для файлов одного репо, берем max() (или first())
repo_metrics = df.groupby("repo")["repo_cov_pct"].max().reset_index()
for index, row in repo_metrics.iterrows():
    print(f"Repo: {row['repo']} -> Total Coverage: {row['repo_cov_pct']}%")

print("\n" + "="*40)
print("SLOWEST MODULES")
print("="*40)
slowest = df.sort_values("gen_time_s", ascending=False).head(5)
print(slowest[["module", "gen_time_s", "status", "file_cov_pct"]])

# ==========================================
# PLOTS FOR THESIS
# ==========================================
sns.set(style="whitegrid", context="paper", font_scale=1.2)

# 1. Status distribution (Pie chart выглядит лучше для Success Rate)
plt.figure(figsize=(8, 5))
status_counts = df["status"].value_counts()
plt.pie(status_counts, labels=status_counts.index, autopct='%1.1f%%', startangle=140, colors=sns.color_palette("pastel"))
plt.title("Test Generation Success Rate (Pynguin)")
plt.tight_layout()
plt.show()

# 2. File Coverage Distribution (Boxplot grouped by Repo)
# Отлично показывает разброс качества тестов в разных репозиториях
plt.figure(figsize=(10, 6))
sns.boxplot(data=df, x="repo", y="file_cov_pct", palette="Set2")
plt.title("File-Level Code Coverage Distribution by Repository")
plt.xlabel("Repository")
plt.ylabel("File Coverage (%)")
plt.xticks(rotation=15)
plt.tight_layout()
plt.show()

# 3. Overall Repository Coverage (Bar Chart)
plt.figure(figsize=(8, 5))
sns.barplot(data=repo_metrics, x="repo", y="repo_cov_pct", palette="viridis")
plt.title("Overall Repository Code Coverage")
plt.xlabel("Repository")
plt.ylabel("Total Coverage (%)")
plt.ylim(0, 100) # Покрытие от 0 до 100
plt.xticks(rotation=15)
plt.tight_layout()
plt.show()

if not generated.empty:
    # 4. Correlation: Generation Time vs Coverage (Scatter plot)
    plt.figure(figsize=(8, 5))
    sns.scatterplot(data=generated, x="gen_time_s", y="file_cov_pct", alpha=0.7, color="b")
    plt.title("Generation Time vs. File Coverage")
    plt.xlabel("Generation Time (seconds)")
    plt.ylabel("File Coverage (%)")
    plt.tight_layout()
    plt.show()

    # 5. Tests per file
    plt.figure(figsize=(8, 5))
    sns.histplot(generated["n_tests"], bins=15, kde=True, color="purple")
    plt.title("Distribution of Generated Tests per File")
    plt.xlabel("Number of Tests")
    plt.ylabel("Frequency")
    plt.tight_layout()
    plt.show()
