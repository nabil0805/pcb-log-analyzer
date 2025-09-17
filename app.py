import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import os

# ---------------------------
# Utility: detect events
# ---------------------------
def detect_events(df):
    events = []
    grouped = df.groupby(["Product", "ComponentRef"])
    
    for (product, comp), group in grouped:
        group = group.sort_values(by="Index").reset_index(drop=True)
        fail_count = 0
        in_episode = False
        fail_batch = None
        
        for i, row in group.iterrows():
            result = row["Result"]
            batch = row["BatchNumber"]

            if result != 0:  # fail
                fail_count += 1
                if fail_count >= 3 and not in_episode:
                    in_episode = True
                    fail_batch = batch
            else:  # pass
                if in_episode:
                    if batch != fail_batch:
                        events.append(["Replenishment", product, comp, fail_batch])
                    else:
                        events.append(["Real Problem", product, comp, fail_batch])
                    in_episode = False
                fail_count = 0
        # ignore unresolved episodes
    return pd.DataFrame(events, columns=["EventType", "Product", "ComponentRef", "BatchNumber"])

# ---------------------------
# Streamlit app
# ---------------------------
st.title("PCB Log Analyzer Dashboard")

uploaded_files = st.file_uploader("Upload CSV log files", accept_multiple_files=True, type=["csv"])

if uploaded_files:
    # Combine CSVs
    dfs = []
    for f in uploaded_files:
        df = pd.read_csv(f)
        dfs.append(df)
    data = pd.concat(dfs, ignore_index=True)

    # Run detection
    events_df = detect_events(data)

    # 🚫 Remove Unknowns once and for all
    events_df = events_df[events_df["EventType"].isin(["Replenishment", "Real Problem"])]

    # Product filter
    products = ["All"] + sorted(events_df["Product"].unique())
    selected_product = st.selectbox("Filter by Product", products)

    filtered = events_df.copy()
    if selected_product != "All":
        filtered = filtered[filtered["Product"] == selected_product]

    st.subheader("Events Summary Table")
    st.dataframe(filtered)

    # ---------------------------
    # Failure stats plot
    # ---------------------------
    st.subheader("Failure Stats (Counts)")
    fail_stats = filtered["EventType"].value_counts()

    fig, ax = plt.subplots()
    fail_stats.plot(kind="bar", ax=ax, color=["#ff7f0e", "#1f77b4"])
    ax.set_ylabel("Count")
    ax.set_title("Failure Statistics")
    st.pyplot(fig)

    # ---------------------------
    # Top problematic components
    # ---------------------------
    st.subheader("Top Problematic Components")
    comp_counts = filtered["ComponentRef"].value_counts().head(10)

    fig2, ax2 = plt.subplots()
    comp_counts.plot(kind="bar", ax=ax2, color="red")
    ax2.set_ylabel("Count")
    ax2.set_title("Top 10 Problematic Components")
    st.pyplot(fig2)

    # ---------------------------
    # Batch correlation
    # ---------------------------
    st.subheader("Fails by Batch")
    batch_counts = filtered.groupby(["BatchNumber", "EventType"]).size().unstack(fill_value=0)

    fig3, ax3 = plt.subplots()
    batch_counts.plot(kind="bar", stacked=True, ax=ax3)
    ax3.set_ylabel("Count")
    ax3.set_title("Batch Correlation")
    st.pyplot(fig3)

    # ---------------------------
    # Download option
    # ---------------------------
    st.subheader("Download Results")
    out_name = "pcb_summary_cleaned.xlsx"
    with pd.ExcelWriter(out_name, engine="xlsxwriter") as writer:
        filtered.to_excel(writer, sheet_name="Events", index=False)
        fail_stats.to_excel(writer, sheet_name="FailureStats")
        comp_counts.to_excel(writer, sheet_name="TopComponents")
        batch_counts.to_excel(writer, sheet_name="BatchCorrelation")

    with open(out_name, "rb") as f:
        st.download_button("Download Excel Summary", f, file_name=out_name)
