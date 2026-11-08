#!/usr/bin/env python3
import argparse
import sys
import math
import json
import itertools
import ctypes
import tkinter as tk
import tkinter.ttk as ttk
from tkinter import filedialog, messagebox
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Line3DCollection
from matplotlib.colors import LinearSegmentedColormap, Normalize
from fgtape_parser import parse_fgtape

__version__ = "1.0.1"

class FgTapeViewer:
    def __init__(self, root):
        self.root = root
        self.root.title("FlightGear fgtape Viewer")
        self.root.geometry("650x700")

        self.meta_info = {}
        self.signals = []
        self.frames_time = []
        self.data_series = {}
        self.selected_props = []
        self.checkbox_vars = []

        self.create_widgets()

    def create_widgets(self):
        top_frame = ttk.LabelFrame(self.root, text="File Information", padding=10)
        top_frame.pack(fill="x", padx=15, pady=10)

        self.btn_open = ttk.Button(top_frame, text="Open fgtape File", command=self.load_file_dialog)
        self.btn_open.pack(anchor="w", pady=5)

        self.lbl_aircraft = ttk.Label(top_frame, text="Aircraft: N/A", anchor="w")
        self.lbl_aircraft.pack(fill="x")

        self.lbl_desc = ttk.Label(top_frame, text="Description: None", anchor="w", justify="left", wraplength=600)
        self.lbl_desc.pack(fill="x")

        self.lbl_duration = ttk.Label(top_frame, text="Duration: N/A", anchor="w")
        self.lbl_duration.pack(fill="x")

        action_frame = ttk.Frame(top_frame)
        action_frame.pack(anchor="w", pady=5)

        self.btn_overview = ttk.Button(action_frame, text="Overview", command=self.plot_overview, state="disabled")
        self.btn_overview.pack(side="left", padx=(0, 5))

        self.btn_export = ttk.Button(action_frame, text="Export Tape to JSON", command=self.export_to_json, state="disabled")
        self.btn_export.pack(side="left")

        mid_frame = ttk.LabelFrame(self.root, text="Select Signals to Plot (Max 2)", padding=10)
        mid_frame.pack(fill="both", expand=True, padx=15, pady=5)

        self.canvas = tk.Canvas(mid_frame, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(mid_frame, orient="vertical", command=self.canvas.yview)
        self.scroll_frame = ttk.Frame(self.canvas)

        self.scroll_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        bottom_frame = ttk.Frame(self.root, padding=(0, 10))
        bottom_frame.pack(fill="x", padx=15)

        self.btn_plot = ttk.Button(bottom_frame, text="Plot Data", width=12, command=self.plot_data, state="disabled")
        self.btn_plot.pack(side="left", padx=5)

        self.btn_clear = ttk.Button(bottom_frame, text="Clear Selection", width=12, command=self.clear_selection, state="disabled")
        self.btn_clear.pack(side="left", padx=5)

        self.btn_about = ttk.Button(bottom_frame, text="About", width=12, command=self.show_about)
        self.btn_about.pack(side="right", padx=5)

    def load_file_dialog(self):
        file_path = filedialog.askopenfilename(
            filetypes=[("FlightGear Tape", "*.fgtape"), ("All Files", "*.*")]
        )
        if file_path:
            self.load_file_path(file_path)

    def load_file_path(self, file_path):
        print(f"Loading file: {file_path}")
        try:
            with open(file_path, "rb") as f:
                content = f.read()

            parsed = parse_fgtape(content)

            self.meta_info = parsed.get("meta", {})
            self.signals = parsed.get("signals", [])
            parsed_data = parsed.get("data", {})

            self.frames_time = parsed_data.get("/sim-time", parsed_data.get("sim-time", []))
            self.data_series = parsed_data

            self.update_ui_after_load()
            print("Successfully parsed the recording tape.")

        except Exception as e:
            print(f"Error occurred while loading file: {e}")
            messagebox.showerror("Error", f"Failed to parse tape:\n{str(e)} ({type(e).__name__})")

    def update_ui_after_load(self):
        aircraft = self.meta_info.get("aircraft-description", "N/A")
        desc = self.meta_info.get("user-data", {}).get("description") or "None"
        duration = self.meta_info.get("tape-duration-str", "N/A")

        self.lbl_aircraft.config(text=f"Aircraft: {aircraft}")
        self.lbl_desc.config(text=f"Description: {desc}")
        self.lbl_duration.config(text=f"Duration: {duration}")

        for child in self.scroll_frame.winfo_children():
            child.destroy()

        self.selected_props = []
        self.checkbox_vars = []
        for sig in self.signals:
            prop_path = sig["property"]
            var = tk.BooleanVar()
            self.checkbox_vars.append(var)
            cb = tk.Checkbutton(
                self.scroll_frame,
                text=prop_path,
                variable=var,
                anchor="w",
                command=lambda p=prop_path, v=var: self.handle_checkbox(p, v)
            )
            cb.pack(fill="x", anchor="w")

        if self.signals and self.frames_time:
            self.btn_overview.config(state="normal")
            self.btn_export.config(state="normal")
            self.btn_plot.config(state="normal")
            self.btn_clear.config(state="normal")
        else:
            self.btn_overview.config(state="disabled")
            self.btn_export.config(state="disabled")
            self.btn_plot.config(state="disabled")
            self.btn_clear.config(state="disabled")

    def handle_checkbox(self, prop_path, var):
        if var.get():
            if len(self.selected_props) >= 2:
                var.set(False)
                messagebox.showwarning("Limit Reached", "You can select a maximum of 2 data channels at once.")
            else:
                self.selected_props.append(prop_path)
        else:
            if prop_path in self.selected_props:
                self.selected_props.remove(prop_path)

    def clear_selection(self):
        """Uncheck all signals and reset the selection list."""
        for var in self.checkbox_vars:
            var.set(False)
        self.selected_props = []

    def show_about(self):
        messagebox.showinfo(
            "About",
            f"""FlightGear fgtape Viewer
Version: {__version__}
Source: github.com/container32/fgtape-viewer"""
        )

    def export_to_json(self):
        """Export the currently loaded tape (meta, signals, data) to a JSON file."""
        if not self.data_series:
            messagebox.showinfo("No File Loaded", "Please load an .fgtape file first.")
            return

        file_path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
            title="Export to JSON",
        )
        if not file_path:
            return

        payload = {
            "meta": self.meta_info,
            "signals": self.signals,
            "data": self.data_series,
        }

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            print(f"Exported JSON to: {file_path}")
            messagebox.showinfo("Export Successful", f"JSON exported successfully:\n{file_path}")
        except Exception as e:
            print(f"Error occurred while exporting JSON: {e}")
            messagebox.showerror("Export Failed", f"Failed to export JSON:\n{str(e)} ({type(e).__name__})")

    def plot_overview(self):
        """Draw the whole flight path in 3D (lon/lat/alt), coloured by ground speed."""
        d = self.data_series
        pos_keys = (
            "/position[0]/longitude-deg[0]",
            "/position[0]/latitude-deg[0]",
            "/position[0]/altitude-ft[0]",
        )
        speed_keys = (
            "/velocities[0]/speed-north-fps[0]",
            "/velocities[0]/speed-east-fps[0]",
            "/velocities[0]/speed-down-fps[0]",
        )
        if not all(k in d and d[k] for k in itertools.chain(pos_keys, speed_keys)):
            messagebox.showerror("Missing Data", "The tape does not contain position and velocity data.")
            return

        lon = d[pos_keys[0]]
        lat = d[pos_keys[1]]
        alt_ft = d[pos_keys[2]]

        n = min(len(lon), len(lat), len(alt_ft))
        lon, lat, alt_ft = lon[:n], lat[:n], alt_ft[:n]

        # Ground speed from north/east/down components (fps -> m/s):
        # sqrt(vn^2+ve^2+vd^2) * 0.3048
        vn, ve, vd = (d[k][:n] for k in speed_keys)
        speed = [math.sqrt(a * a + b * b + c * c) * 0.3048
                for a, b, c in zip(vn, ve, vd)]

        # Convert lon/lat to local metric offsets so the path is not distorted.
        # z uses the absolute altitude (not relative to the start point).
        lat0 = math.radians(lat[0])
        m_per_deg_lat = 111320.0
        m_per_deg_lon = 111320.0 * math.cos(lat0)
        x = [(lo - lon[0]) * m_per_deg_lon for lo in lon]   # east,  m
        y = [(la - lat[0]) * m_per_deg_lat for la in lat]   # north, m
        z = [a * 0.3048 for a in alt_ft]                    # alt,   m (absolute)

        fig = plt.figure(figsize=(10, 7))
        fig.canvas.manager.set_window_title("Flight Path Overview") # type: ignore
        ax = fig.add_subplot(111, projection="3d")

        if speed and any(s > 0 for s in speed):
            # Yellow (slow) -> Blue (fast)
            cmap = LinearSegmentedColormap.from_list("slow_fast", ["yellow", "green", "blue"])
            norm = Normalize(vmin=min(speed), vmax=max(speed))

            pts = list(zip(x, y, z))
            segs = [[pts[i], pts[i + 1]] for i in range(len(pts) - 1)]
            seg_speed = [0.5 * (speed[i] + speed[i + 1]) for i in range(len(segs))]

            lc = Line3DCollection(segs, cmap=cmap, norm=norm, linewidth=2)
            lc.set_array(seg_speed)
            ax.add_collection3d(lc)

            sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
            sm.set_array([])
            cb = fig.colorbar(sm, ax=ax, shrink=0.6, pad=0.1)
            cb.set_label("Ground Speed (m/s)")
        else:
            ax.plot(x, y, z, color="tab:blue", linewidth=1.5)

        # Start / end markers
        ax.scatter([x[0]], [y[0]], [z[0]], color="green", s=60, label="Start")
        ax.scatter([x[-1]], [y[-1]], [z[-1]], color="red", s=60, label="End")
        ax.legend(loc="upper right")

        ax.set_xlabel("East offset (m)")
        ax.set_ylabel("North offset (m)")
        ax.set_zlabel("Altitude (m)")

        # Equal-ish aspect so the path is not visually squashed
        xmid = (max(x) + min(x)) / 2.0
        ymid = (max(y) + min(y)) / 2.0
        zmid = (max(z) + min(z)) / 2.0
        half = max(max(x) - min(x), max(y) - min(y), max(z) - min(z), 1.0) / 2.0
        ax.set_xlim(xmid - half, xmid + half)
        ax.set_ylim(ymid - half, ymid + half)
        ax.set_zlim(zmid - half, zmid + half)

        ax.view_init(elev=0, azim=-60)

        ax.set_title("Flight Path Overview (Drag to Rotate)")
        plt.tight_layout()
        plt.show()

    def plot_data(self):
        if not self.selected_props:
            messagebox.showinfo("No Selection", "Please check at least one signal parameter to plot.")
            return

        if len(self.selected_props) == 1:
            fig, ax1 = plt.subplots(figsize=(9, 5))
            prop = self.selected_props[0]
            ax1.plot(self.frames_time, self.data_series[prop], color="tab:blue", linewidth=1.5)
            ax1.set_xlabel("Time (seconds)")
            ax1.set_ylabel(prop, color="tab:blue")
            ax1.tick_params(axis="y", labelcolor="tab:blue")
            ax1.grid(True, linestyle="--", alpha=0.6)
            ax1.set_title(prop)

        elif len(self.selected_props) == 2:
            fig, ax1 = plt.subplots(figsize=(10, 5))
            prop1, prop2 = self.selected_props[0], self.selected_props[1]

            ax1.plot(self.frames_time, self.data_series[prop1], color="tab:blue", label=prop1, linewidth=1.5)
            ax1.set_xlabel("Time (seconds)")
            ax1.set_ylabel(prop1, color="tab:blue")
            ax1.tick_params(axis="y", labelcolor="tab:blue")
            ax1.grid(True, linestyle="--", alpha=0.6)

            ax2 = ax1.twinx()
            ax2.plot(self.frames_time, self.data_series[prop2], color="tab:orange", label=prop2, linewidth=1.5)
            ax2.set_ylabel(prop2, color="tab:orange")
            ax2.tick_params(axis="y", labelcolor="tab:orange")

            ax1.set_title(f"{prop1} and {prop2}")
            fig.tight_layout()

        plt.show()


def main():
    if sys.platform == "win32":
        ctypes.OleDLL('shcore').SetProcessDpiAwareness(1)

    parser = argparse.ArgumentParser(description="FlightGear fgtape Viewer")
    parser.add_argument("fgtape_file", nargs="?", help="Optional path to an .fgtape file")
    args = parser.parse_args()

    root = tk.Tk()
    app = FgTapeViewer(root)

    if args.fgtape_file:
        app.load_file_path(args.fgtape_file)

    root.mainloop()

if __name__ == "__main__": main()
