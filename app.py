import os
import sys
import uuid
import logging
from datetime import datetime
from flask import Flask, request, send_file, jsonify, after_this_request

# Make mcp_local importable regardless of CWD
_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_ROOT, "mcp_local"))

from generate_weekly_report import generate_weekly_report  # noqa: E402

app = Flask(__name__)

UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", os.path.join(_ROOT, "uploads"))
OUTPUT_FOLDER = os.environ.get("OUTPUT_FOLDER", os.path.join(_ROOT, "outputs"))
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


# ── Routes ──────────────────────────────────────────────────────────────────

@app.route("/generate", methods=["POST"])
def generate():
    if "csv_file" not in request.files:
        return jsonify({"error": "No file uploaded."}), 400

    f = request.files["csv_file"]
    if not f.filename or not f.filename.lower().endswith(".csv"):
        return jsonify({"error": "Please upload a valid .csv file."}), 400

    # Save upload to a temp path
    tmp_name = f"{uuid.uuid4().hex}.csv"
    csv_path = os.path.join(UPLOAD_FOLDER, tmp_name)
    f.save(csv_path)

    # Timestamped output PDF
    stamp    = datetime.now().strftime("%Y%m%d_%H%M%S")
    pdf_name = f"weekly_report_{stamp}.pdf"
    pdf_path = os.path.join(OUTPUT_FOLDER, pdf_name)

    try:
        result = generate_weekly_report(csv_path=csv_path, output_pdf=pdf_path)
    except Exception as e:
        logging.error(f"Report generation failed: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        # Always remove the temp CSV
        if os.path.exists(csv_path):
            os.remove(csv_path)

    return jsonify({
        "status":           "success",
        "filename":         pdf_name,
        "total_tickets":    result["total_tickets"],
        "sla_violated":     result["sla_violated"],
        "sla_rate":         result["sla_rate"],
        "escalated_count":  result["escalated_count"],
        "escalation_rate":  result["escalation_rate"],
        "resolved_count":   result["resolved_count"],
        "resolution_rate":  result["resolution_rate"],
        "avg_per_day":      result["avg_per_day"],
        "teams_covered":    result["teams_covered"],
    })


@app.route("/download/<filename>")
def download(filename):
    safe = os.path.basename(filename)
    path = os.path.join(OUTPUT_FOLDER, safe)
    if not os.path.exists(path):
        return jsonify({"error": "File not found."}), 404

    @after_this_request
    def _cleanup(response):
        try:
            os.remove(path)
        except Exception:
            pass
        return response

    return send_file(path, as_attachment=True, download_name=safe,
                     mimetype="application/pdf")


# ── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port  = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("DEBUG", "false").lower() == "true"
    print(f"\n  Weekly Report Web App  →  http://localhost:{port}\n")
    app.run(debug=debug, port=port)
