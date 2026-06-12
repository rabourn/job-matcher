# Manual job-ad evidence

Drop PDFs of job ads here (print-to-PDF from the browser works fine). On its
next run, the pipeline reads each PDF, matches it to the job in the ledger by
company and title, and uses the ad as verification evidence: the role is
scored with the ad's full text, work mode, and any posted date, instead of
being penalized as unverified.

Processed files are renamed with a .processed- prefix so they are only read
once. Naming the file anything readable is fine; matching uses the PDF's
content, not the filename.
