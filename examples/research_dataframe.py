"""Example of preparing cached prices as a clean DataFrame for factor analysis."""
from M_TSE import M_TSE

tse = M_TSE(data_dir="tse_data")
possible = tse.archive.find("خودرو")
print(possible[["Ticker", "Name", "Type"]].head(15))
if not possible.empty:
    iid = possible.index[0]
    frame = tse.archive.history(iid, adjusted=False)
    if frame.empty:
        print("No saved prices yet: sync the ID before running this analysis.")
    else:
        frame = frame.sort_values("Date")
        frame["Return_1D"] = frame["Close"].pct_change()
        frame["Volume_MA20"] = frame["Volume"].rolling(20).mean()
        print(frame.tail(10))
