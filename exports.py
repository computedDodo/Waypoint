import os
import csv
import io
import zipfile
from flask import current_app, send_file
from models import Submission, Task


def build_campaign_export(campaign):
    """Returns a Flask response streaming a zip of submissions.csv plus
    every attached screenshot for the given campaign."""
    submissions = Submission.query.join(Task).filter(Task.campaign_id == campaign.id).all()

    csv_buffer = io.StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerow(['Tester', 'Mission', 'Status', 'Points Awarded', 'Claimed At',
                      'Submitted At', 'Reviewed At', 'Tester Notes', 'Admin Feedback', 'Screenshot Files'])
    for sub in submissions:
        filenames = '; '.join(f.file_path for f in sub.files)
        writer.writerow([
            sub.tester.username, sub.task.title, sub.status, sub.points_awarded,
            sub.claimed_at, sub.submitted_at or '', sub.reviewed_at or '',
            sub.tester_notes or '', sub.admin_feedback or '', filenames,
        ])

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('submissions.csv', csv_buffer.getvalue())
        for sub in submissions:
            for f in sub.files:
                abs_path = os.path.join(current_app.root_path, 'static', f.file_path)
                if os.path.exists(abs_path):
                    zf.write(abs_path, arcname=f'screenshots/{os.path.basename(f.file_path)}')
    zip_buffer.seek(0)

    safe_name = ''.join(c if c.isalnum() else '_' for c in campaign.name)
    return send_file(
        zip_buffer,
        as_attachment=True,
        download_name=f'{safe_name}_export.zip',
        mimetype='application/zip',
    )
