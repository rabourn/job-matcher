# Manual job-ad evidence

Drop PDFs of job ads here (print-to-PDF from the browser works fine). On its
next run, the pipeline reads each PDF in this folder, scores the role against
your brief and overrides using the ad's full text, work mode, and any posted
date, and adds it to the report and ledger as verified manual evidence (no
unverified penalty, since you vouched for it).

After processing, each PDF is moved into `processed/` so it is read once.
Naming the file anything readable is fine; matching uses the PDF's content,
not the filename.

Use this for roles you find by hand, especially ones the LinkedIn-alert
pipeline cannot verify (recruiter-confidential or Gulf-government postings),
and want scored alongside everything else.
