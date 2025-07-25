import os
import time
import requests
import pandas as pd
import streamlit as st
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import re
from io import BytesIO

# ========== Configuration ==========
WAIT_BETWEEN_REQUESTS = 1  # seconds
USER_AGENT = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    )
}
# ===================================

def extract_category_and_metro(url):
    try:
        parts = urlparse(url).path.strip("/").split("/")
        category = parts[0].replace("-", " ") if len(parts) > 0 else "unknown"
        metro = parts[1].replace("-", " ") if len(parts) > 1 else "unknown"
        return category, metro
    except Exception:
        return "unknown", "unknown"

def extract_category_urls(df, column_name):
    urls = df[column_name].dropna().unique()
    base_urls = set()

    for full_url in urls:
        try:
            parsed = urlparse(full_url)
            parts = parsed.path.strip("/").split("/")
            if len(parts) >= 2:
                base_url = f"{parsed.scheme}://{parsed.netloc}/{parts[0]}/{parts[1]}"
                base_urls.add(base_url)
        except Exception:
            continue

    return list(base_urls)

def scrape_company_data(url):
    try:
        st.write(f"🔍 Scraping category page: {url}")
        response = requests.get(url, headers=USER_AGENT, timeout=10)
        if response.status_code != 200:
            st.warning(f"⚠️ Skipping {url} — status code {response.status_code}")
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        category, metro = extract_category_and_metro(url)
        results = []

        company_blocks = soup.find_all("div", class_="company-row")

        for position, block in enumerate(company_blocks, start=1):
            name_tag = block.find("meta", attrs={"itemprop": "name"})
            name = name_tag["content"].strip() if name_tag and name_tag.has_attr("content") else "N/A"

            if name and name != "N/A":
                results.append({
                    "url": url,
                    "category": category,
                    "metro": metro,
                    "position": position,
                    "name": name
                })

        st.success(f"✅ Found {len(results)} companies")
        return results

    except Exception as e:
        st.error(f"❌ Error scraping {url}: {e}")
        return []

def normalize(text):
    if not isinstance(text, str):
        return ""
    text = text.lower()
    text = text.replace("&", "and")
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def main():
    st.title("🔎 FiveStar Seasonal Web Proofing")
    uploaded_file = st.file_uploader("Upload CSV file with 'Company Web Profile URL' and 'PublishedName':", type="csv")

    if uploaded_file:
        df = pd.read_csv(uploaded_file)
        if "FSR Position" not in df.columns:
            st.warning("Input file is missing 'FSR Position' column. Generating it automatically.")
            df["FSR Position"] = df.groupby(["Metro", "Category"])["PublishedName"].rank(method="first").astype(int)

        urls = extract_category_urls(df, "Company Web Profile URL")
        st.write(f"📄 Found `{len(urls)}` unique category/metro URLs")

        all_data = []
        progress = st.progress(0)
        for i, url in enumerate(urls, 1):
            data = scrape_company_data(url)
            all_data.extend(data)
            progress.progress(i / len(urls))
            time.sleep(WAIT_BETWEEN_REQUESTS)

        if all_data:
            out_df = pd.DataFrame(all_data)

            # === Comparison Step ===
            st.subheader("📊 Comparison Results")
            df["Metro"] = df["Metro"].fillna("").astype(str)
            out_df["metro"] = out_df["metro"].fillna("").astype(str)

            df["match_key"] = (
                df["PublishedName"].apply(normalize) + "|" +
                df["Category"].apply(normalize) + "|" +
                df["Metro"].apply(normalize)
            )
            out_df["match_key"] = (
                out_df["name"].apply(normalize) + "|" +
                out_df["category"].apply(normalize) + "|" +
                out_df["metro"].apply(normalize)
            )

            merged = pd.merge(out_df, df, on="match_key", how="left", suffixes=("_output", "_input"))
            merged["comparison_issue"] = ""

            merged.loc[merged["PublishedName"].isna(), "comparison_issue"] = "missing from input"
            merged.loc[
                (merged["comparison_issue"] == "") &
                (merged["position"].notna()) &
                (merged["FSR Position"].notna()) &
                (merged["position"] != merged["FSR Position"]),
                "comparison_issue"
            ] = "position mismatch"

            scraped_keys = set(out_df["match_key"])
            input_keys = set(df["match_key"])
            missing_keys = input_keys - scraped_keys

            missing_rows = df[df["match_key"].isin(missing_keys)].copy()
            missing_rows["comparison_issue"] = "missing from website"
            missing_rows["name"] = None
            missing_rows["url"] = None
            missing_rows["category"] = missing_rows["Category"]
            missing_rows["metro"] = missing_rows["Metro"]
            missing_rows["position"] = None

            final_df = pd.concat([merged, missing_rows], ignore_index=True)

            # Show result preview
            st.dataframe(final_df[["PublishedName", "name", "category", "metro", "FSR Position", "position", "comparison_issue"]].fillna(""))

            # Download link
            towrite = BytesIO()
            final_df.to_excel(towrite, index=False)
            towrite.seek(0)
            st.download_button(
                label="📥 Download Comparison Results",
                data=towrite,
                file_name="fivestar_comparison_results.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.warning("No company data was found.")

if __name__ == "__main__":
    main()
