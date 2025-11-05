from datetime import datetime, timezone
import tkinter as tk
from tkinter import ttk, messagebox

import numpy as np
import pandas as pd
import threading
import concurrent.futures as conf

from utils import compute_metrics_for_ticker, read_tickers_from_file
from vars import *



# -------------------------------
# Tkinter App
# -------------------------------
class DrawdownApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Drawdown Monitor — Tkinter")
        self.geometry("1080x660")

        style = ttk.Style(self)
        try:
            style.theme_use(THEME)
        except Exception:
            pass

        style.configure(
            "Custom.Treeview",
            rowheight=26,
            bordercolor="#000000",
            borderwidth=1,
            relief="solid",
            background="#FFFFFF",
            fieldbackground="#FFFFFF",
            highlightthickness=1
        )
        style.configure(
            "Custom.Treeview.Heading",
            bordercolor="#000000",
            borderwidth=1,
            relief="solid",
            background="#F5F7FA",
            foreground="#000000"
        )

        self.sort_state = {}
        self.current_sort_col = None
        self.current_sort_asc = True
        self.heading_labels = {
            "ticker": "Ticker",
            "current_price": "Current Price",
            "historical_max": "Historical Max (High)",
            "current_draw_down_pct": "Current Drawdown (%)",
            "recover_ratio": "Recover Ratio (%)",
            "error": "Error",
        }

        self._build_controls()

        self._build_table()

        self.tickers_file = DEFAULT_TICKERS_FILE
        self.refresh_sec = REFRESH_INTERVAL_SEC
        self.after_id = None
        self.loading = False

        self.start_refresh_loop()

    def _build_controls(self):
        frm = ttk.Frame(self, padding=(12, 8))
        frm.pack(side=tk.TOP, fill=tk.X)

        ttk.Label(frm, text="Tickers File:").pack(side=tk.LEFT)
        self.entry_file = ttk.Entry(frm, width=42)
        self.entry_file.insert(0, DEFAULT_TICKERS_FILE)
        self.entry_file.pack(side=tk.LEFT, padx=6)

        ttk.Label(frm, text="Refresh (sec):").pack(side=tk.LEFT, padx=(12, 0))
        self.entry_interval = ttk.Entry(frm, width=6, justify="right")
        self.entry_interval.insert(0, str(REFRESH_INTERVAL_SEC))
        self.entry_interval.pack(side=tk.LEFT, padx=6)

        self.btn_apply = ttk.Button(frm, text="Apply", command=self.on_apply)
        self.btn_apply.pack(side=tk.LEFT, padx=(6, 0))

        self.btn_refresh_now = ttk.Button(frm, text="Refresh Now", command=self.refresh_once)
        self.btn_refresh_now.pack(side=tk.LEFT, padx=6)

        self.lbl_status = ttk.Label(frm, text="Ready", foreground="#555")
        self.lbl_status.pack(side=tk.RIGHT)

    def _build_table(self):
        cols_visible = ("ticker", "current_price", "historical_max",
                        "current_draw_down_pct", "recover_ratio", "error")
        cols_hidden = ("_cur_raw", "_hist_raw", "_dd_raw", "_rr_raw")
        columns = cols_visible + cols_hidden

        self.tree = ttk.Treeview(
            self, columns=columns, show="headings", height=20, style="Custom.Treeview"
        )
        self.tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        for col in cols_visible:
            self.tree.heading(col, text=self.heading_labels[col],
                              command=lambda c=col: self.on_heading_click(c))

        for col in cols_hidden:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=0, stretch=False)

        self.tree.column("ticker", width=110, anchor=tk.CENTER)
        self.tree.column("current_price", width=140, anchor=tk.E)
        self.tree.column("historical_max", width=180, anchor=tk.E)
        self.tree.column("current_draw_down_pct", width=180, anchor=tk.E)
        self.tree.column("recover_ratio", width=160, anchor=tk.E)
        self.tree.column("error", width=240, anchor=tk.W)

        self.tree.tag_configure("oddrow", background=ODD_ROW_BG)
        self.tree.tag_configure("evenrow", background=EVEN_ROW_BG)

        self.tree.configure(takefocus=True)
        self.tree.configure(selectmode="browse")
        self.tree.configure(cursor="arrow")
        try:
            self.tree.configure(highlightbackground="#000000", highlightthickness=1)
        except Exception:
            pass

    def on_apply(self):
        path = self.entry_file.get().strip()
        if not path:
            messagebox.showwarning("Input Error", "Enter path to tickers file ")
            return
        self.tickers_file = path

        try:
            sec = int(float(self.entry_interval.get()))
            if sec < 5:
                raise ValueError
        except Exception:
            messagebox.showwarning("Input Error", "Refresh (sec) must be larger than 5.")
            return
        self.refresh_sec = sec

        self.refresh_once()
        self.start_refresh_loop()

    def start_refresh_loop(self):
        if self.after_id is not None:
            try: self.after_cancel(self.after_id)
            except Exception: pass
            self.after_id = None
        self.after_id = self.after(self.refresh_sec * 1000, self._refresh_loop_callback)

    def _refresh_loop_callback(self):
        self.refresh_once()
        self.start_refresh_loop()

    def refresh_once(self):
        if self.loading:
            return
        self.loading = True

        self.lbl_status.config(text="Loading...")
        self.update_idletasks()

        tickers = read_tickers_from_file(self.tickers_file)
        if not tickers:
            self.lbl_status.config(text=f"No tickers in {self.tickers_file}")
            for iid in self.tree.get_children():
                self.tree.delete(iid)
            self.loading = False
            return

        def worker_collect():
            rows = []
            max_workers = min(MAX_WORKERS, len(tickers)) or 1
            with conf.ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ddw") as ex:
                futures = {ex.submit(compute_metrics_for_ticker, tkc): tkc for tkc in tickers}
                done_cnt = 0
                for fut in conf.as_completed(futures):
                    tkc = futures[fut]
                    try:
                        m = fut.result()
                    except Exception as e:
                        m = {
                            "ticker": tkc,
                            "current_price": np.nan,
                            "historical_max": np.nan,
                            "current_draw_down_pct": np.nan,
                            "recover_ratio": np.nan,
                            "error": str(e),
                            "_cur_raw": float("nan"),
                            "_hist_raw": float("nan"),
                            "_dd_raw": float("nan"),
                            "_rr_raw": float("nan"),
                        }
                    rows.append(m)
                    done_cnt += 1
                    self.after(0, self.lbl_status.config, {"text": f"Loading... {done_cnt}/{len(tickers)}"})

            def on_main_thread():
                df = pd.DataFrame(rows)
                if self.current_sort_col:
                    df = self._apply_sort_to_dataframe(df, self.current_sort_col, self.current_sort_asc)
                else:
                    # 최초엔 recover_ratio 내림차순
                    if "recover_ratio" in df.columns:
                        df.sort_values(by="recover_ratio", ascending=False, inplace=True, na_position="last")
                df.reset_index(drop=True, inplace=True)

                self._update_tree(df)
                self._refresh_heading_arrows()

                now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                self.lbl_status.config(text=f"Last update: {now_utc}")
                self.loading = False

            self.after(0, on_main_thread)

        threading.Thread(target=worker_collect, daemon=True).start()

    def _apply_sort_to_dataframe(self, df: pd.DataFrame, col: str, asc: bool) -> pd.DataFrame:
        col_map_raw = {
            "current_price": "_cur_raw",
            "historical_max": "_hist_raw",
            "current_draw_down_pct": "_dd_raw",
            "recover_ratio": "_rr_raw",
        }
        sort_col = col_map_raw.get(col, col)
        if sort_col not in df.columns:
            return df
        return df.sort_values(
            by=sort_col,
            ascending=asc,
            na_position="last"
        )

    def _update_tree(self, df: pd.DataFrame):
        for iid in self.tree.get_children():
            self.tree.delete(iid)

        for i, row in df.iterrows():
            vals_visible = (
                row.get("ticker", ""),
                self._fmt_num(row.get("current_price")),
                self._fmt_num(row.get("historical_max")),
                self._fmt_pct(row.get("current_draw_down_pct")),
                self._fmt_pct(row.get("recover_ratio")),
                row.get("error", ""),
            )
            vals_hidden = (
                row.get("_cur_raw", float("nan")),
                row.get("_hist_raw", float("nan")),
                row.get("_dd_raw", float("nan")),
                row.get("_rr_raw", float("nan")),
            )
            vals = vals_visible + vals_hidden

            tags = []
            if i % 2 == 1:
                tags.append("oddrow")
            else:
                tags.append("evenrow")

            if row.get("error"):
                err_tag = f"err_{i}"
                try:
                    self.tree.tag_configure(err_tag, foreground="#B00020")
                    tags.append(err_tag)
                except Exception:
                    pass
            self.tree.insert("", tk.END, values=vals, tags=tags)

    def _refresh_heading_arrows(self):
        for c, label in self.heading_labels.items():
            if self.current_sort_col and c == self.current_sort_col:
                arrow = " ▲" if self.current_sort_asc else " ▼"
                self.tree.heading(c, text=label + arrow)
            else:
                self.tree.heading(c, text=label)

    @staticmethod
    def _fmt_num(v):
        try:
            if pd.isna(v):
                return ""
            return f"{float(v):,.{ROUND_DIGITS}f}"
        except Exception:
            return str(v)

    @staticmethod
    def _fmt_pct(v):
        try:
            if pd.isna(v):
                return ""
            return f"{float(v):+.{ROUND_DIGITS}f}%"
        except Exception:
            return str(v)

    def on_heading_click(self, col: str):
        if self.current_sort_col == col:
            self.current_sort_asc = not self.current_sort_asc
        else:
            self.current_sort_col = col
            self.current_sort_asc = True

        self._sort_tree_in_place(self.current_sort_col, self.current_sort_asc)
        self._refresh_heading_arrows()

    def _sort_tree_in_place(self, col: str, asc: bool):
        col_map_raw = {
            "current_price": "_cur_raw",
            "historical_max": "_hist_raw",
            "current_draw_down_pct": "_dd_raw",
            "recover_ratio": "_rr_raw",
        }
        sort_col = col_map_raw.get(col, col)
        cols = self.tree["columns"]
        try:
            idx = cols.index(sort_col)
        except ValueError:
            return

        items = []
        for iid in self.tree.get_children(""):
            vals = self.tree.item(iid, "values")
            key_val = vals[idx] if idx < len(vals) else ""
            if sort_col.startswith("_"):
                try: k = float(key_val)
                except Exception: k = float("nan")
            elif col in ("current_price", "historical_max", "current_draw_down_pct", "recover_ratio"):
                k = self._parse_number_like(key_val)
            else:
                k = (key_val or "").upper()
            items.append((iid, k))

        def sort_key(pair):
            _, k = pair
            if isinstance(k, float) and (np.isnan(k) or k is None):
                return (1, 0)
            return (0, k)

        items.sort(key=sort_key, reverse=not asc)
        for index, (iid, _) in enumerate(items):
            self.tree.move(iid, "", index)
        
        self._reapply_row_colors()
    
    def _reapply_row_colors(self):
        """
        현재 표시 순서 기준으로 zebra 색을 다시 적용하고,
        error 값이 있는 행은 ERROR_BG로 덮어씌움.
        """
        cols = self.tree["columns"]
        try:
            err_idx = cols.index("error")
        except ValueError:
            err_idx = None

        self.tree.tag_configure("oddrow", background=ODD_ROW_BG)
        self.tree.tag_configure("evenrow", background=EVEN_ROW_BG)
        self.tree.tag_configure("errorbg", background=ERROR_BG)

        for i, iid in enumerate(self.tree.get_children("")):
            old_tags = list(self.tree.item(iid, "tags") or [])
            new_tags = [t for t in old_tags if t not in ("oddrow", "evenrow", "errorbg")]

            has_error = False
            if err_idx is not None:
                vals = self.tree.item(iid, "values")
                if err_idx < len(vals) and str(vals[err_idx]).strip():
                    has_error = True

            if has_error:
                new_tags.append("errorbg")
            else:
                new_tags.append("oddrow" if i % 2 == 1 else "evenrow")

            self.tree.item(iid, tags=new_tags)

    @staticmethod
    def _parse_number_like(s):
        try:
            if s is None or s == "":
                return float("nan")
            s = str(s).replace(",", "").replace("%", "").replace("+", "")
            return float(s)
        except Exception:
            return float("nan")

# -------------------------------
# Run
# -------------------------------
if __name__ == "__main__":
    try:
        app = DrawdownApp()
        app.mainloop()
    except Exception as e:
        messagebox.showerror("Fatal Error", str(e))