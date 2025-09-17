import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import os
import io

# Failure code meanings
failure_meanings = {
    2: "Rejected by vision before electrical test",
    3: "Rejected by vision after electrical test",
    4: "Rejected by electrical test",
    5: "Not placed (lost after electrical test)",
    6: "Not taken by the machine",
    7: "Rejected by vision before pick-up"
}

st.title("📊 PCB Placement Log Analysis Dashboard")

uploaded_files = st.file_uploader("Upload one or more log CSV files", type="csv", accept_multiple_files=True)

if uploaded_files:
    all_halts = []
    replenishments = []
    all_data = []
    skipped_rows_log = []

    for uploaded_file in uploaded_files:
        filename = uploaded_file.name

        # --- Step 1: Product name from row 1 col 2 ---
        try:
            header_df = pd.read_csv(uploaded_file, encoding="latin1", nrows=2, header=None, engine="python")
            product_name = header_df.iloc[0, 1] if header_df.shape[1] > 1 else "Unknown"
        except Exception:
            product_name = "Unknown"

        # reset pointer for actual read
        uploaded_file.seek(0)

        # --- Step 2: Load log data, skip first 2 rows ---
        try:
            df = pd.read_csv(
                uploaded_file,
                encoding="latin1",
                skiprows=2,
                usecols=range(12),
                on_bad_lines=lambda x: skipped_rows_log.append((filename, x)) or None,
                engine="python"
            )
        except Exception as e:
            st.error(f"Skipping {filename}, error reading file: {e}")
            continue

        # --- Step 3: Rename columns ---
        df = df.rename(columns={
            df.columns[1]: "PartNumber",
            df.columns[2]: "Description",
            df.columns[3]: "Reference",
            df.columns[6]: "BatchNumber",
            df.columns[11]: "Result"
        })
        df_relevant = df[["PartNumber", "Description", "Reference", "BatchNumber", "Result"]].dropna()
        df_relevant["Result"] = pd.to_numeric(df_relevant["Result"], errors="coerce").fillna(0).astype(int)
        df_relevant["ProductName"] = product_name
        df_relevant["File"] = filename
        all_data.append(df_relevant)

        # --- Step 4: Detect halts & replenishments ---
        for part, group in df_relevant.groupby("PartNumber"):
            group = group.reset_index(drop=True)
            n = len(group)
            i = 0
            while i <= n - 3:
                # Look for 3 consecutive fails
                if group.loc[i, "Result"] != 0 and group.loc[i+1, "Result"] != 0 and group.loc[i+2, "Result"] != 0:
                    batch_here = str(group.loc[i, "BatchNumber"]).strip()
                    main_fail = group.loc[i, "Result"]

                    # Find next pass (Result == 0)
                    future_pass = group.loc[i+3:][group["Result"] == 0]
                    if not future_pass.empty:
                        next_pass_idx = future_pass.index[0]
                        next_batch = str(group.loc[next_pass_idx, "BatchNumber"]).strip()
                        if next_batch != batch_here:
                            replenishments.append({
                                "ProductName": product_name,
                                "File": filename,
                                "PartNumber": group.loc[i, "PartNumber"],
                                "Description": group.loc[i, "Description"],
                                "Reference": group.loc[i, "Reference"],
                                "BatchNumber": batch_here,
                                "MainFailType": failure_meanings.get(main_fail, "Unknown failure")
                            })
                        else:
                            all_halts.append({
                                "ProductName": product_name,
                                "File": filename,
                                "PartNumber": group.loc[i, "PartNumber"],
                                "Description": group.loc[i, "Description"],
                                "Reference": group.loc[i, "Reference"],
                                "BatchNumber": batch_here,
                                "MainFailType": failure_meanings.get(main_fail, "Unknown failure")
                            })
                    # Collapse whole episode until after the pass/fail run
                    if not future_pass.empty:
                        i = next_pass_idx + 1
                    else:
                        i += 3
                else:
                    i += 1

    # --- Build dataframes ---
    summary_df = pd.DataFrame(all_halts)
    replenishments_df = pd.DataFrame(replenishments)
    all_data_df = pd.concat(all_data, ignore_index=True) if all_data else pd.DataFrame()

    # --- Product filter ---
    product_filter = st.selectbox(
        "Filter by Product (optional)", 
        options=["All"] + sorted(all_data_df["ProductName"].unique().tolist())
    )

    if product_filter != "All":
        summary_df = summary_df[summary_df["ProductName"] == product_filter]
        replenishments_df = replenishments_df[replenishments_df["ProductName"] == product_filter]
        all_data_df = all_data_df[all_data_df["ProductName"] == product_filter]

    st.subheader("📌 Real Problems (Halts)")
    st.dataframe(summary_df)

    st.subheader("🔄 Replenishments")
    st.dataframe(replenishments_df)

    # --- Failure Stats ---
    fail_counts_df = pd.DataFrame()
    if not summary_df.empty:
        fail_counts_df = summary_df["MainFailType"].value_counts().reset_index()
        fail_counts_df.columns = ["FailureType", "Count"]
        st.subheader("Failure Stats")
        st.dataframe(fail_counts_df)

        fig, ax = plt.subplots()
        fail_counts_df.plot.pie(y="Count", labels=fail_counts_df["FailureType"], autopct='%1.1f%%', ax=ax)
        ax.set_ylabel("")
        st.pyplot(fig)

    # --- Halts by Product ---
    product_counts_df = pd.DataFrame()
    if not summary_df.empty:
        product_counts_df = summary_df["ProductName"].value_counts().reset_index()
        product_counts_df.columns = ["ProductName", "Halts"]
        st.subheader("Halts by Product")
        st.dataframe(product_counts_df)

        fig, ax = plt.subplots()
        ax.bar(product_counts_df["ProductName"], product_counts_df["Halts"])
        plt.xticks(rotation=45)
        st.pyplot(fig)

    # --- Top Problematic Components ---
    component_counts_df = pd.DataFrame()
    if not summary_df.empty:
        component_counts_df = summary_df["PartNumber"].value_counts().reset_index()
        component_counts_df.columns = ["PartNumber", "Halts"]
        st.subheader("Top Problematic Components")
        st.dataframe(component_counts_df)

        fig, ax = plt.subplots()
        ax.bar(component_counts_df["PartNumber"], component_counts_df["Halts"])
        plt.xticks(rotation=45)
        st.pyplot(fig)

    # --- Fails by Batch ---
    batch_counts_df = pd.DataFrame()
    if not summary_df.empty:
        batch_counts_df = summary_df["BatchNumber"].value_counts().reset_index()
        batch_counts_df.columns = ["BatchNumber", "Halts"]
        st.subheader("Fails by Batch")
        st.dataframe(batch_counts_df)

        fig, ax = plt.subplots()
        ax.bar(batch_counts_df["BatchNumber"], batch_counts_df["Halts"])
        plt.xticks(rotation=45)
        st.pyplot(fig)

    # --- Batch Fail Correlation ---
    batch_corr = pd.DataFrame()
    if not summary_df.empty:
        st.subheader("Batch Fail Correlation")
        batch_corr = pd.crosstab(summary_df["BatchNumber"], summary_df["MainFailType"])
        st.dataframe(batch_corr)

        fig, ax = plt.subplots(figsize=(8,6))
        im = ax.imshow(batch_corr, cmap="Blues")
        ax.set_xticks(range(len(batch_corr.columns)))
        ax.set_xticklabels(batch_corr.columns, rotation=45)
        ax.set_yticks(range(len(batch_corr.index)))
        ax.set_yticklabels(batch_corr.index)
        for i in range(len(batch_corr.index)):
            for j in range(len(batch_corr.columns)):
                ax.text(j, i, batch_corr.iloc[i, j], ha="center", va="center", color="black")
        st.pyplot(fig)

    # --- Excel Export ---
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        summary_df.to_excel(writer, sheet_name="Summary", index=False)
        replenishments_df.to_excel(writer, sheet_name="Replenishments", index=False)
        fail_counts_df.to_excel(writer, sheet_name="Failure Stats", index=False)
        product_counts_df.to_excel(writer, sheet_name="Halts by Product", index=False)
        component_counts_df.to_excel(writer, sheet_name="Top Problematic Components", index=False)
        batch_counts_df.to_excel(writer, sheet_name="Fails by Batch", index=False)
        batch_corr.to_excel(writer, sheet_name="Batch Fail Correlation")

    st.download_button(
        label="💾 Download Excel Summary",
        data=output.getvalue(),
        file_name="pcb_analysis_summary.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    st.success(f"✅ Analysis complete. Found {len(summary_df)} real problems and {len(replenishments_df)} replenishments.")

else:
    st.info("Please upload one or more CSV log files to begin analysis.")
