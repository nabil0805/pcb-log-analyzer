import os
import pandas as pd
import streamlit as st

# ----------------------------
# Failure code meanings
# ----------------------------
failure_meanings = {
    2: "Rejected by vision before electrical test",
    3: "Rejected by vision after electrical test",
    4: "Rejected by electrical test",
    5: "Not placed (lost after electrical test)",
    6: "Not taken by the machine",
    7: "Rejected by vision before pick-up"
}


# ----------------------------
# Analysis function
# ----------------------------
def analyze_logs(file_paths):
    all_halts = []
    replenishments = []
    all_data = []
    skipped_rows_log = []

    for file_path in file_paths:
        filename = os.path.basename(file_path)

        # --- Step 1: Product name from cell B1
        try:
            header_df = pd.read_csv(
                file_path,
                encoding="latin1",
                nrows=2,
                header=None,
                engine="python",
                on_bad_lines="skip"
            )
            product_name = header_df.iloc[0, 1] if header_df.shape[1] > 1 else "Unknown"
        except Exception:
            product_name = "Unknown"

        # --- Step 2: Load actual log data
        try:
            df = pd.read_csv(
                file_path,
                encoding="latin1",
                skiprows=2,
                usecols=range(12),
                on_bad_lines=lambda x: skipped_rows_log.append((filename, x)) or None,
                engine="python"
            )
        except Exception as e:
            st.warning(f"Skipping {filename}, error reading file: {e}")
            continue

        # --- Step 3: Rename columns
        df = df.rename(columns={
            df.columns[1]: "PartNumber",
            df.columns[2]: "Description",
            df.columns[3]: "Reference",
            df.columns[6]: "BatchNumber",
            df.columns[11]: "Result"
        })

        df_relevant = df[["PartNumber", "Description", "Reference", "BatchNumber", "Result"]].dropna()
        df_relevant["Result"] = pd.to_numeric(df_relevant["Result"], errors="coerce").fillna(0).astype(int)

        # keep all attempts
        df_relevant["ProductName"] = product_name
        df_relevant["File"] = filename
        all_data.append(df_relevant)

        # --- Step 4: Detect halts/replenishments
        for part, group in df_relevant.groupby("PartNumber"):
            group = group.reset_index(drop=True)
            n = len(group)
            i = 0

            while i <= n - 3:
                r0, r1, r2 = group.loc[i, "Result"], group.loc[i + 1, "Result"], group.loc[i + 2, "Result"]

                # Three consecutive fails (and must be known failures)
                if r0 in failure_meanings and r1 in failure_meanings and r2 in failure_meanings:
                    batch_here = str(group.loc[i, "BatchNumber"]).strip()

                    # Find the next passing attempt (Result == 0)
                    next_pass = group[(group.index > i + 2) & (group["Result"] == 0)].head(1)

                    fail_codes = [r0, r1, r2]
                    fail_text = ", ".join(
                        f"{code} → {failure_meanings.get(code)}" for code in fail_codes
                    )
                    main_fail = fail_codes[0]

                    if not next_pass.empty:
                        next_batch = str(next_pass["BatchNumber"].values[0]).strip()
                        if next_batch != batch_here:
                            replenishments.append({
                                "ProductName": product_name,
                                "File": filename,
                                "PartNumber": group.loc[i, "PartNumber"],
                                "Description": group.loc[i, "Description"],
                                "Reference": group.loc[i, "Reference"],
                                "BatchNumber": batch_here,
                                "FailCodes": fail_text,
                                "MainFailType": failure_meanings[main_fail]
                            })
                        else:
                            all_halts.append({
                                "ProductName": product_name,
                                "File": filename,
                                "PartNumber": group.loc[i, "PartNumber"],
                                "Description": group.loc[i, "Description"],
                                "Reference": group.loc[i, "Reference"],
                                "BatchNumber": batch_here,
                                "FailCodes": fail_text,
                                "MainFailType": failure_meanings[main_fail]
                            })

                    i += 3
                    continue
                i += 1

    return (
        pd.DataFrame(all_halts),
        pd.DataFrame(replenishments),
        pd.concat(all_data, ignore_index=True) if all_data else pd.DataFrame()
    )


# ----------------------------
# Streamlit App
# ----------------------------
st.title("PCB Log Analysis Dashboard")

uploaded_files = st.file_uploader(
    "Upload multiple CSV log files",
    type=["csv"],
    accept_multiple_files=True
)

if uploaded_files:
    if st.button("Run Analysis"):
        file_paths = []
        for f in uploaded_files:
            temp_path = os.path.join("temp_uploaded_" + f.name)
            with open(temp_path, "wb") as tmp:
                tmp.write(f.getbuffer())
            file_paths.append(temp_path)

        halts_df, replenishments_df, all_data_df = analyze_logs(file_paths)

        st.session_state["halts"] = halts_df
        st.session_state["repls"] = replenishments_df
        st.session_state["all_data"] = all_data_df

# ----------------------------
# Results Section
# ----------------------------
if "halts" in st.session_state:
    halts_df = st.session_state["halts"]
    replenishments_df = st.session_state["repls"]
    all_data_df = st.session_state["all_data"]

    # Product filter
    all_products = sorted(all_data_df["ProductName"].unique())
    product_choice = st.selectbox("Filter by Product", ["All"] + all_products)

    if product_choice != "All":
        halts_df = halts_df[halts_df["ProductName"] == product_choice]
        replenishments_df = replenishments_df[replenishments_df["ProductName"] == product_choice]
        all_data_df = all_data_df[all_data_df["ProductName"] == product_choice]

    st.subheader("Halts")
    st.dataframe(halts_df)

    st.subheader("Replenishments")
    st.dataframe(replenishments_df)

    st.subheader("Failure Stats")
    if not halts_df.empty:
        fail_counts_df = halts_df["MainFailType"].value_counts().reset_index()
        fail_counts_df.columns = ["FailureType", "Count"]
        st.dataframe(fail_counts_df)

    st.subheader("Halts by Product")
    if not halts_df.empty:
        product_counts_df = halts_df["ProductName"].value_counts().reset_index()
        product_counts_df.columns = ["ProductName", "Halts"]
        st.dataframe(product_counts_df)

    st.subheader("Top Problematic Components")
    if not halts_df.empty:
        component_counts_df = halts_df["PartNumber"].value_counts().reset_index()
        component_counts_df.columns = ["PartNumber", "Halts"]
        st.dataframe(component_counts_df)

    st.subheader("Fails by Batch")
    if not halts_df.empty:
        batch_counts_df = halts_df["BatchNumber"].value_counts().reset_index()
        batch_counts_df.columns = ["BatchNumber", "Halts"]
        st.dataframe(batch_counts_df)

    st.subheader("Batch Fail Correlation")
    if not halts_df.empty:
        batch_corr = pd.crosstab(halts_df["BatchNumber"], halts_df["MainFailType"])
        st.dataframe(batch_corr)
