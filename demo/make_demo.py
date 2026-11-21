import os, subprocess, textwrap

OUT = r"C:\Users\loren\Documents\AntiGravity Projects\diligent\demo"
os.makedirs(OUT, exist_ok=True)
HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)

W = 92
def body(*paras):
    lines = []
    for p in paras:
        if p == "":
            lines.append("")
        elif p.startswith("  "):
            lines += textwrap.wrap(p, W, initial_indent="", subsequent_indent="    ") or [""]
        else:
            lines += textwrap.wrap(p, W) or [""]
    return "\n".join(lines)

SLIDES = [
    (6, "Payper Trail", body("Transaction-monitoring alert triage", "Fin Crime Hackathon, Track 1", "",
                             "Andrei  ·  Clotilde  ·  Lorenzo  ·  Fedya")),
    (11, "The problem", body(
        "An alert fires on a customer. An analyst reads the transactions, the customer profile, the documents, earlier "
        "reviews and the internal list, and closes the case with one verdict:", "",
        "  CLOSE  the evidence explains every alert",
        "  RFI  nothing suspicious yet, one document would settle it (and we say which)",
        "  ESCALATE  unexplained activity or signs of crime, to the MLRO", "",
        "Closing a case that needed an RFI or an escalation costs 10. Four institutions, four different policies, "
        "4,000 development cases, 800 unseen.")),
    (13, "How it decides: the SOP decides, the model only reads", body(
        "1. Load the case and parse each institution's POLICY.md at run time (thresholds, 5x rule, invoice rule).",
        "2. Red flags: positive signs of crime from the evidence (listed person still in control, fraud reports, "
        "invoices that don't fit, money passed to new linked companies, structuring questions).",
        "3. Explainers: documents that explain an alert, checked in code to the penny (payee, holder, dates).",
        "4. Reader: a decision model answers narrow yes/no questions about chats and emails. It can never close a case.",
        "5. Rulebook: per alert red flag > explained > one document missing > rule default. The worst alert wins.",
        "6. Check: reason code fits the verdict, every cited ID exists.")),
    (12, "Case 1: same name, same birth date  →  ESCALATE", body(
        "A £19,507.30 'gift' comes from someone with the same name as an exited customer on the internal list. "
        "The gift letter gives the payer's date of birth: it is the listed person's.", "",
        "Reason written by the system:",
        "  \"Riley Selholt is the listed person in IV-L25058 (exited customer ... refusing to explain large cash "
        "deposits): their date of birth matches (GFT-6016), and they are the counterparty on the payment date "
        "13 August 2026.\"")),
    (12, "Case 2: same name, different person  →  CLOSE", body(
        "Another gift, another name match on the list. This time the letter gives a birth date 40 years apart.", "",
        "Reason written by the system:",
        "  \"Jules Glencombe matched list entry IV-L36466 on name only: GFT-3507 gives their birth as 10 July 1997, "
        "but the listed person was born 8 August 1957, so they are a different person. GFT-3507 documents the "
        "£16,885.30 received on 13 October 2026 as a gift ..., for the same amount.\"")),
    (12, "Case 3: invoices written after the money moved  →  ESCALATE", body(
        "A catering-equipment importer pays a Hong Kong supplier; the invoices on file are for mobile phones.", "",
        "Reason written by the system:",
        "  \"The invoices on file do not support the payments: INV 18412 is for £242,008.78 but £212,288.40 was paid; "
        "INV 18412 is dated 7 October 2026, after the payment on 4 October 2026 ...\"")),
    (12, "Results on the 4,000 development cases", body(
        "                     CLOSE / RFI / ESCALATE     team labels right     wrongful closes",
        "  Bank               500 / 250 / 250            83 / 83               0",
        "  E-money            500 / 250 / 250            78 / 78               0",
        "  Investment         500 / 250 / 250            85 / 85               0",
        "  Payments and FX    499 / 251 / 250            80 / 80               0", "",
        "A Grok labeller working blind (no access to our labels or outputs) agrees on 3,996 of 4,000 verdicts; 251 of its answers were revised after a second look.")),
    (11, "Built to be trusted", body(
        "Reproducible: 5 runs with an empty model cache give the same verdict and code on 4,000 / 4,000 cases.",
        "Explainable: every decision has a trace with the rule path, the evidence, the quoted SOP clause and each model answer.",
        "Fast and cheap: a few seconds per 1,000 cases; under a cent per 200 cases for the model calls.",
        "Safe by construction: a model answer alone can never close a case.")),
    (5, "github.com/firdavz/diligent", body("system/run <institution folder> <output file>", "", "Thank you")),
]

FONT_B = r"C\:/Windows/Fonts/segoeuib.ttf"
FONT_R = r"C\:/Windows/Fonts/consola.ttf"
parts = []
for n, (dur, title, text) in enumerate(SLIDES):
    open(f"t{n}.txt", "w", encoding="utf-8", newline="\n").write(title)
    open(f"b{n}.txt", "w", encoding="utf-8", newline="\n").write(text)
    big = n in (0, len(SLIDES) - 1)
    vf = (f"drawtext=fontfile='{FONT_B}':textfile=t{n}.txt:expansion=none:fontcolor=white:fontsize={96 if big else 58}:"
          f"x={'(w-text_w)/2' if big else 110}:y={330 if big else 90},"
          f"drawbox=x=110:y={460 if big else 175}:w={1700 if big else 220}:h=4:color=0x38bdf8:t=fill,"
          f"drawtext=fontfile='{FONT_R}':textfile=b{n}.txt:expansion=none:fontcolor=0xdbe4ee:fontsize={40 if big else 33}:"
          f"line_spacing=16:x={'(w-text_w)/2' if big else 110}:y={510 if big else 230},"
          f"fade=t=in:st=0:d=0.4,fade=t=out:st={dur - 0.4}:d=0.4")
    out = f"s{n}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=0x0f172a:s=1920x1080:d={dur}:r=30",
                    "-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p", out], check=True)
    parts.append(out)
open("list.txt", "w").write("".join(f"file '{p}'\n" for p in parts))
final = os.path.join(OUT, "payper_trail_demo.mp4")
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", final], check=True)
print(final, sum(s[0] for s in SLIDES), "seconds")
