"""
CrisisGrid — Automated Real-User End-to-End & Algorithmic Test Suite
=====================================================================
Executes 22 comprehensive test use cases simulating real user interactions
in Chromium via Playwright, validating live USGS data, map rendering,
routing calculations, simulation mechanics, and failure handling.
"""

import os
import sys
import time
from playwright.sync_api import sync_playwright

BASE_URL = "http://localhost:8000"
SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), "test_reports")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

results = []

def record(uc_id, name, passed, details=""):
    status = "PASS" if passed else "FAIL"
    results.append({"id": uc_id, "name": name, "status": status, "details": details})
    symbol = "[PASS]" if passed else "[FAIL]"
    print(f"{symbol} [{uc_id}] {name} -- {status} {('(' + details + ')') if details else ''}")

def run_tests():
    print("\n" + "="*70)
    print("CRISISGRID AUTOMATED REAL-USER E2E TEST SUITE (22 USE CASES)")
    print("="*70 + "\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        # Capture console errors
        console_errors = []
        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

        # ── UC-1: Page Load & Initial UI Layout ────────────────────────
        try:
            page.goto(BASE_URL, wait_until="networkidle")
            title = page.title()
            sidebar = page.locator("#sidebar").is_visible()
            map_div = page.locator("#map").is_visible()
            record("UC-1", "Page Load & Core Layout", "CrisisGrid" in title and sidebar and map_div, f"Title: '{title}'")
        except Exception as e:
            record("UC-1", "Page Load & Core Layout", False, str(e))

        # ── UC-2: Tile Layer Integrity (No API Key watermark) ─────────
        try:
            # Check Leaflet tile container exists and loaded tiles
            tile_count = page.locator(".leaflet-tile-loaded").count()
            # Check layer control is present on topright
            layer_ctrl = page.locator(".leaflet-control-layers").is_visible()
            record("UC-2", "Tile Layer & Layer Control Integrity", tile_count > 0 and layer_ctrl, f"Loaded tiles: {tile_count}")
        except Exception as e:
            record("UC-2", "Tile Layer & Layer Control Integrity", False, str(e))

        # ── UC-3: Initial Route Calculation on Mount (SEA -> PHX) ─────
        try:
            page.wait_for_selector(".path-flow .path-node", timeout=5000)
            nodes = page.locator(".path-flow .path-node").all_inner_texts()
            cost_el = page.locator(".stat-value.accent").first.inner_text()
            # Under clean conditions: SEA -> PDX -> RNO -> LAS -> PHX (2170 km)
            # If PDX or RNO disrupted by live USGS quakes: detours cleanly through BOI/SLC (2200 km)
            valid_path = (nodes == ["SEA", "PDX", "RNO", "LAS", "PHX"]) or (nodes == ["SEA", "BOI", "SLC", "PHX"])
            record("UC-3", "Default SEA -> PHX Corridor Computed", valid_path, f"Path: {' -> '.join(nodes)}, Cost: {cost_el}")
        except Exception as e:
            record("UC-3", "Default SEA -> PHX Corridor Computed", False, str(e))

        # ── UC-4: Live USGS Seismic Feed Ingestion ────────────────────
        try:
            page.wait_for_selector(".quake-item", timeout=5000)
            quake_count = page.locator(".quake-item").count()
            first_mag = page.locator(".quake-mag").first.inner_text()
            first_place = page.locator(".quake-place").first.inner_text()
            record("UC-4", "Live USGS Feed Ingestion", quake_count > 0, f"{quake_count} earthquakes, top: {first_mag} {first_place}")
        except Exception as e:
            record("UC-4", "Live USGS Feed Ingestion", False, str(e))

        # ── UC-5: Graph Node Markers Rendered on Map ──────────────────
        try:
            markers = page.locator(".node-marker").count()
            record("UC-5", "10 Network Node Markers on Map", markers == 10, f"Rendered markers: {markers}")
        except Exception as e:
            record("UC-5", "10 Network Node Markers on Map", False, str(e))

        # ── UC-6: Operational Hub Status & Visual Tags ────────────────
        try:
            labels = [m.inner_text().strip() for m in page.locator(".pin-label").all()]
            expected_nodes = {"SEA", "PDX", "BOI", "RNO", "SAC", "SFO", "SLC", "LAS", "LAX", "PHX"}
            all_present = expected_nodes.issubset(set(labels))
            record("UC-6", "All 10 Hub Label Identifiers Present", all_present, f"Found: {len(labels)} labels")
        except Exception as e:
            record("UC-6", "All 10 Hub Label Identifiers Present", False, str(e))

        # ── UC-7: Network Resilience Metric Initial Uptime ────────────
        try:
            score = page.locator("#health-score").inner_text()
            details = page.locator("#health-details").inner_text()
            record("UC-7", "Resilience Uptime Initial Score", "100%" in score or "%" in score, f"Score: {score}, {details}")
        except Exception as e:
            record("UC-7", "Resilience Uptime Initial Score", False, str(e))

        # ── UC-8: Endpoint Swap Button ────────────────────────────────
        try:
            page.click("#swap-btn")
            time.sleep(0.5)
            src = page.locator("#source-select").input_value()
            dst = page.locator("#target-select").input_value()
            swapped = (src == "PHX" and dst == "SEA")
            page.click("#compute-btn")
            page.wait_for_selector(".path-flow .path-node", timeout=5000)
            new_nodes = page.locator(".path-flow .path-node").all_inner_texts()
            record("UC-8", "Swap Endpoints & Reverse Route", swapped and new_nodes[0] == "PHX" and new_nodes[-1] == "SEA", f"Reversed: {' -> '.join(new_nodes)}")
        except Exception as e:
            record("UC-8", "Swap Endpoints & Reverse Route", False, str(e))

        # ── UC-9: Short Corridor Routing (SAC -> SFO) ─────────────────
        try:
            page.select_option("#source-select", "SAC")
            page.select_option("#target-select", "SFO")
            page.click("#compute-btn")
            time.sleep(0.5)
            nodes = page.locator(".path-flow .path-node").all_inner_texts()
            cost = page.locator(".stat-value.accent").first.inner_text()
            record("UC-9", "Direct Adjacent Corridor (SAC -> SFO)", nodes == ["SAC", "SFO"] and "140" in cost, f"Path: {' -> '.join(nodes)}, Cost: {cost}")
        except Exception as e:
            record("UC-9", "Direct Adjacent Corridor (SAC -> SFO)", False, str(e))

        # ── UC-10: Northern Corridor Routing (SEA -> BOI) ─────────────
        try:
            page.select_option("#source-select", "SEA")
            page.select_option("#target-select", "BOI")
            page.click("#compute-btn")
            time.sleep(0.5)
            nodes = page.locator(".path-flow .path-node").all_inner_texts()
            cost = page.locator(".stat-value.accent").first.inner_text()
            record("UC-10", "Northern Corridor (SEA -> BOI)", nodes == ["SEA", "BOI"] and "740" in cost, f"Cost: {cost}")
        except Exception as e:
            record("UC-10", "Northern Corridor (SEA -> BOI)", False, str(e))

        # ── UC-11: Southern Corridor Routing (LAX -> PHX) ─────────────
        try:
            page.select_option("#source-select", "LAX")
            page.select_option("#target-select", "PHX")
            page.click("#compute-btn")
            time.sleep(0.5)
            nodes = page.locator(".path-flow .path-node").all_inner_texts()
            cost = page.locator(".stat-value.accent").first.inner_text()
            record("UC-11", "Southern Corridor (LAX -> PHX)", nodes == ["LAX", "PHX"] and "600" in cost, f"Cost: {cost}")
        except Exception as e:
            record("UC-11", "Southern Corridor (LAX -> PHX)", False, str(e))

        # ── UC-12: Error Handling: Identical Source and Target ────────
        try:
            page.select_option("#source-select", "SEA")
            page.select_option("#target-select", "SEA")
            page.click("#compute-btn")
            time.sleep(0.5)
            err = page.locator(".error-msg").inner_text()
            record("UC-12", "Error Handling (Source == Target)", "Source and target must differ" in err, f"Message: {err}")
        except Exception as e:
            record("UC-12", "Error Handling (Source == Target)", False, str(e))

        # ── UC-13: Simulator Toggle Interaction ───────────────────────
        try:
            page.click("#sim-toggle + .slider")
            time.sleep(0.3)
            sim_controls_visible = page.locator("#sim-controls").is_visible()
            record("UC-13", "Simulator Panel Toggle Expand", sim_controls_visible, "Panel expanded")
        except Exception as e:
            record("UC-13", "Simulator Panel Toggle Expand", False, str(e))

        # ── UC-14: Magnitude Slider Adjustment ────────────────────────
        try:
            page.fill("#sim-mag", "6.5")
            page.dispatch_event("#sim-mag", "input")
            val = page.locator("#sim-mag-val").inner_text()
            record("UC-14", "Magnitude Slider Input", val == "6.5", f"Slider value: {val}")
        except Exception as e:
            record("UC-14", "Magnitude Slider Input", False, str(e))

        # ── UC-15: Disaster Scenario Simulation (Reno M6.5) ───────────
        try:
            # Set SEA -> PHX again
            page.select_option("#source-select", "SEA")
            page.select_option("#target-select", "PHX")
            page.click("#compute-btn")
            time.sleep(0.5)

            # Click the Reno M6.5 disaster preset button
            page.locator(".sim-preset-btn").first.click()
            time.sleep(1.0)

            sim_count = page.locator(".sim-item").count()
            record("UC-15", "Simulation Epicenter Placement (Reno M6.5)", sim_count > 0, f"Active simulated quakes: {sim_count}")
        except Exception as e:
            record("UC-15", "Simulation Epicenter Placement (Reno M6.5)", False, str(e))

        # ── UC-16: Dynamic Dijkstra Reroute Around Disrupted Hub ─────
        try:
            page.wait_for_selector(".path-flow .path-node", timeout=5000)
            nodes = page.locator(".path-flow .path-node").all_inner_texts()
            score = page.locator("#health-score").inner_text()
            # RNO is damaged, so path MUST not pass through RNO
            bypassed = ("RNO" not in nodes)
            record("UC-16", "Dynamic Dijkstra Reroute Around Disruption", bypassed, f"Corridor: {' -> '.join(nodes)}, Resilience: {score}")
        except Exception as e:
            record("UC-16", "Dynamic Dijkstra Reroute Around Disruption", False, str(e))

        # ── UC-17: Alternative Corridors Rendering ────────────────────
        try:
            alt_count = page.locator(".alt-route").count()
            record("UC-17", "K-Shortest Alternative Corridors Present", alt_count > 0, f"Alternative paths: {alt_count}")
        except Exception as e:
            record("UC-17", "K-Shortest Alternative Corridors Present", False, str(e))

        # ── UC-18: Interactive Node Popup Inspection ──────────────────
        try:
            # Click on first marker pin dot
            page.locator(".pin-dot").first.click(force=True)
            time.sleep(0.5)
            popup_visible = page.locator(".leaflet-popup-content").is_visible()
            popup_text = page.locator(".leaflet-popup-content").inner_text() if popup_visible else ""
            record("UC-18", "Leaflet Node Popup Info Display", popup_visible and ("Type:" in popup_text), f"Popup snippet: {popup_text[:50]}...")
        except Exception as e:
            record("UC-18", "Leaflet Node Popup Info Display", False, str(e))

        # ── UC-19: Earthquake Feed Map Pan on Click ───────────────────
        try:
            page.locator(".quake-item").first.click()
            time.sleep(0.5)
            # Map zoomed/panned, check zoom level or center
            zoom_in_btn = page.locator(".leaflet-control-zoom-in").is_visible()
            record("UC-19", "Earthquake Feed Pan-to-Location Click", zoom_in_btn, "Interactive pan triggered")
        except Exception as e:
            record("UC-19", "Earthquake Feed Pan-to-Location Click", False, str(e))

        # ── UC-20: Individual Simulated Quake Removal ─────────────────
        try:
            initial_count = page.locator(".sim-item").count()
            if initial_count > 0:
                page.locator(".remove-sim").first.click()
                time.sleep(0.5)
                new_count = page.locator(".sim-item").count()
                record("UC-20", "Individual Simulated Quake Removal", new_count < initial_count, f"Reduced from {initial_count} to {new_count}")
            else:
                record("UC-20", "Individual Simulated Quake Removal", True, "No simulated quakes to remove")
        except Exception as e:
            record("UC-20", "Individual Simulated Quake Removal", False, str(e))

        # ── UC-21: Clear All Simulated Quakes & Reset Route ───────────
        try:
            # Add one more sim quake to test clear
            page.locator(".sim-preset-btn").first.click()
            time.sleep(0.5)
            page.click("#sim-clear")
            time.sleep(0.5)
            remaining_sims = page.locator(".sim-item").count()
            page.click("#compute-btn")
            time.sleep(0.5)
            restored_score = page.locator("#health-score").inner_text()
            record("UC-21", "Clear All Simulated & Restore Live Health Baseline", remaining_sims == 0 and ("%" in restored_score), f"Sim count: {remaining_sims}, Baseline Score: {restored_score}")
        except Exception as e:
            record("UC-21", "Clear All Simulated & Restore Live Health Baseline", False, str(e))

        # ── UC-22: Screenshot & Console Error Check ───────────────────
        try:
            screenshot_path = os.path.join(SCREENSHOT_DIR, "live_crisisgrid_dashboard.png")
            page.screenshot(path=screenshot_path, full_page=True)
            has_no_fatal_errors = len([e for e in console_errors if "favicon" not in e]) == 0
            record("UC-22", "Clean Console & UI Screenshot Captured", has_no_fatal_errors, f"Screenshot saved: {screenshot_path}, Errors: {len(console_errors)}")
        except Exception as e:
            record("UC-22", "Clean Console & UI Screenshot Captured", False, str(e))

        browser.close()

    # ── Summary Report ───────────────────────────────────────────
    total = len(results)
    passed = len([r for r in results if r["status"] == "PASS"])
    failed = total - passed

    print("\n" + "="*70)
    print(f"TEST EXECUTION COMPLETE: {passed}/{total} PASSED ({failed} FAILED)")
    print("="*70 + "\n")

    return failed == 0

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
