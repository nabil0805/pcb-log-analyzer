import os
import pandas as pd
import streamlit as st

# ----------------------------
# Failure code meaningss
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

        # --- Step 2: Load actual log data (keep 12 columns as before)
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
            df.columns[7]: "ColumnH",   # <-- Added
            df.columns[8]: "ColumnI",   # <-- Added
            df.columns[11]: "Result"
        })

        # Include new columns (H, I)
        df_relevant = df[["PartNumber", "Description", "Reference", "BatchNumber", "ColumnH", "ColumnI", "Result"]].dropna(subset=["PartNumber"])
        df_relevant["Result"] = pd.to_numeric(df_relevant["Result"], errors="coerce").fillna(0).astype(int)

        df_relevant["ProductName"] = product_name
        df_relevant["File"] = filename
        df_relevant["FilePath"] = file_path  # keep path for later lookup
        all_data.append(df_relevant)

        # --- Step 4: Detect halts/replenishments (unchanged)
        for part, group in df_relevant.groupby("PartNumber"):
            group = group.reset_index(drop=True)
            n = len(group)
            i = 0

            while i <= n - 3:
                r0, r1, r2 = group.loc[i, "Result"], group.loc[i + 1, "Result"], group.loc[i + 2, "Result"]

                # Three consecutive fails (known failures only)
                if r0 in failure_meanings and r1 in failure_meanings and r2 in failure_meanings:
                    batch_here = str(group.loc[i, "BatchNumber"]).strip()
                    next_pass = group[(group.index > i + 2) & (group["Result"] == 0)].head(1)

                    fail_codes = [r0, r1, r2]
                    fail_text = ", ".join(
                        f"{code} → {failure_meanings.get(code)}" for code in fail_codes
                    )
                    main_fail = fail_codes[0]

                    event = {
                        "ProductName": product_name,
                        "File": filename,
                        "FilePath": file_path,
                        "PartNumber": group.loc[i, "PartNumber"],
                        "Description": group.loc[i, "Description"],
                        "Reference": group.loc[i, "Reference"],
                        "BatchNumber": batch_here,
                        "ColumnH": group.loc[i, "ColumnH"],  # Added
                        "ColumnI": group.loc[i, "ColumnI"],  # Added
                        "FailCodes": fail_text,
                        "MainFailType": failure_meanings[main_fail]
                    }

                    if not next_pass.empty:
                        next_batch = str(next_pass["BatchNumber"].values[0]).strip()
                        if next_batch != batch_here:
                            replenishments.append(event)
                        else:
                            all_halts.append(event)
                    else:
                        all_halts.append(event)
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

    # ---------------- Halts ----------------
    st.subheader("Halts")
    if not halts_df.empty:
        halts_df = halts_df.reset_index(drop=True)
        st.dataframe(halts_df)

        selected_idx = st.number_input(
            "Enter halt row number to inspect details (from table above)",
            min_value=0,
            max_value=len(halts_df) - 1,
            step=1,
            key="halt_select"
        )

        if st.button("Show halt details"):
            selected_halt = halts_df.loc[selected_idx]
            file_path = selected_halt["FilePath"]
            part_num = selected_halt["PartNumber"]

            # Re-read that specific file
            df = pd.read_csv(
                file_path,
                encoding="latin1",
                skiprows=2,
                usecols=range(12),
                engine="python",
                on_bad_lines="skip"
            )
            df = df.rename(columns={
                df.columns[1]: "PartNumber",
                df.columns[2]: "Description",
                df.columns[3]: "Reference",
                df.columns[6]: "BatchNumber",
                df.columns[7]: "ColumnH",   # Added
                df.columns[8]: "ColumnI",   # Added
                df.columns[11]: "Result"
            })
            subset = df[df["PartNumber"] == part_num].copy().reset_index()
            subset.rename(columns={"index": "RowNumber"}, inplace=True)

            st.write(f"All placements for part {part_num} in file {selected_halt['File']}")
            st.dataframe(subset)

    # ---------------- Replenishments ----------------
    st.subheader("Replenishments")
    if not replenishments_df.empty:
        replenishments_df = replenishments_df.reset_index(drop=True)
        st.dataframe(replenishments_df)

        selected_idx_repl = st.number_input(
            "Enter replenishment row number to inspect details (from table above)",
            min_value=0,
            max_value=len(replenishments_df) - 1,
            step=1,
            key="repl_select"
        )

        if st.button("Show replenishment details"):
            selected_repl = replenishments_df.loc[selected_idx_repl]
            file_path = selected_repl["FilePath"]
            part_num = selected_repl["PartNumber"]

            # Re-read that specific file
            df = pd.read_csv(
                file_path,
                encoding="latin1",
                skiprows=2,
                usecols=range(12),
                engine="python",
                on_bad_lines="skip"
            )
            df = df.rename(columns={
                df.columns[1]: "PartNumber",
                df.columns[2]: "Description",
                df.columns[3]: "Reference",
                df.columns[6]: "BatchNumber",
                df.columns[7]: "ColumnH",   # Added
                df.columns[8]: "ColumnI",   # Added
                df.columns[11]: "Result"
            })
            subset = df[df["PartNumber"] == part_num].copy().reset_index()
            subset.rename(columns={"index": "RowNumber"}, inplace=True)

            st.write(f"All placements for part {part_num} in file {selected_repl['File']}")
            st.dataframe(subset)


