#!/usr/bin/env python3
"""render-help.py — build help.html from TROUBLESHOOTING.md.

help.html is GENERATED. Edit TROUBLESHOOTING.md or the symptom cards below,
then re-run this; editing help.html directly works until the next build and
then silently loses the change. selftest.sh regenerates and compares, so a
stale help.html fails the suite rather than quietly shipping wrong advice.

Two audiences, one file:

  the client   plain-language symptom cards. Their job is to identify what
               they are seeing and run ONE safe read-only command. Almost no
               real fix is theirs to make, and pretending otherwise gets a
               non-technical person into System Settings unsupervised.

  their agent  a copy-able handoff prompt, plus the full operator guide
               rendered underneath.

stdlib only — this runs on a built machine where python3 exists but nothing
has been npm-installed.
"""
import html
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent

# ── the client-facing layer ──────────────────────────────────────────────────
# Ordered by how often it actually happens, not by severity. "I don't know"
# is last and catches everything, because a symptom picker with no escape
# hatch sends people away rather than to the diagnostic.
CARDS = [
    ("My morning text didn't arrive",
     "The machine sends a usage summary each morning. If it stopped, the job "
     "behind it is either failing or never fired — those look identical from "
     "the outside, which is why the command below reports both.",
     "bash ~/srv/wb-setup/doctor.sh > /tmp/doctor.txt",
     "Send /tmp/doctor.txt. The answer is in it."),

    ("I can't reach it from my phone",
     "The machine is reachable over a private network. If one page fails, "
     "that page is down. If EVERY page fails at once, the machine has "
     "usually dropped off the network entirely — often an expired key, which "
     "happens on a schedule and is not something you did.",
     "bash ~/srv/wb-setup/doctor.sh > /tmp/doctor.txt",
     "Note whether ONE thing broke or EVERYTHING did — that single detail "
     "usually identifies the cause."),

    ("Claude won't start, or says command not found",
     "Almost always the terminal has not picked up its location yet. This is "
     "the one thing worth trying yourself.",
     "open -a Terminal",
     "Close every terminal window, open a fresh one, and try again. If it "
     "still fails, send the doctor file."),

    ("My work sessions disappeared",
     "Your named sessions are written down and can be rebuilt. The layout "
     "inside them may not come back, but the sessions themselves will.",
     "tm-standard apply",
     "Safe to run — it only creates what is missing and never closes "
     "anything you have open."),

    ("Something says permission denied",
     "macOS permissions occasionally need re-granting, particularly after a "
     "system update. These live in System Settings and are worth doing "
     "together rather than alone — one wrong toggle is hard to spot later.",
     None,
     "Don't work through Settings on your own. Send the doctor file and we "
     "will do it on a call."),

    ("It worked for weeks and now it doesn't",
     "Usually something expired or an update moved a file — a login token, a "
     "network key, a system upgrade resetting a permission. Nothing you did.",
     "bash ~/srv/wb-setup/doctor.sh > /tmp/doctor.txt",
     "Mention roughly when it last worked. That narrows it faster than "
     "anything else."),

    ("I don't know what's wrong",
     "Fine — this is the right place to start. The command below collects "
     "everything about the machine's state in one file.",
     "bash ~/srv/wb-setup/doctor.sh > /tmp/doctor.txt",
     "Send it with a sentence about what you were doing."),
]

AGENT_PROMPT = """This machine was built with wb-setup. Something is wrong:
<describe what you are seeing, and roughly when it last worked>

Please:
1. Run: bash ~/srv/wb-setup/doctor.sh
2. Run: bash ~/srv/wb-setup/verify.sh
3. Read ~/srv/wb-setup/TROUBLESHOOTING.md. Every failure is tagged with an
   ID like [P0-FDA]; each ID has a section with the cause, the fix, and how
   to prove it is fixed.
4. Work the failures in phase order. Fix what you can.
5. STOP and tell me if a fix needs a macOS permission dialog, a password,
   or a paid account — those need a human and I will do them with you.

Report what you changed and how you proved it worked."""


# ── the smallest markdown subset that renders this guide ─────────────────────
def md(src: str) -> str:
    out, i, lines = [], 0, src.split("\n")
    while i < len(lines):
        ln = lines[i]

        if ln.startswith("```"):                       # fenced code
            i += 1
            buf = []
            while i < len(lines) and not lines[i].startswith("```"):
                buf.append(html.escape(lines[i])); i += 1
            i += 1
            out.append("<pre><code>" + "\n".join(buf) + "</code></pre>")
            continue

        if ln.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|$", lines[i + 1]):
            head = [c.strip() for c in ln.strip("|").split("|")]
            i += 2
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip("|").split("|")]); i += 1
            out.append("<table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head)
                       + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows)
                       + "</tbody></table>")
            continue

        if re.match(r"^\s*[-*]\s+", ln):                # bullets
            buf = []
            while i < len(lines) and re.match(r"^\s*[-*]\s+", lines[i]):
                buf.append(f"<li>{inline(re.sub(r'^\\s*[-*]\\s+', '', lines[i]))}</li>"); i += 1
            out.append("<ul>" + "".join(buf) + "</ul>")
            continue

        if re.match(r"^\d+\.\s+", ln):                  # numbered
            buf = []
            while i < len(lines) and re.match(r"^\d+\.\s+", lines[i]):
                buf.append(f"<li>{inline(re.sub(r'^\\d+\\.\\s+', '', lines[i]))}</li>"); i += 1
            out.append("<ol>" + "".join(buf) + "</ol>")
            continue

        if ln.startswith("#"):
            lvl = len(ln) - len(ln.lstrip("#"))
            txt = ln[lvl:].strip()
            anchor = re.sub(r"[^a-z0-9]+", "-", txt.lower()).strip("-")
            out.append(f'<h{lvl} id="{anchor}">{inline(txt)}</h{lvl}>')
            i += 1
            continue

        if ln.strip() in ("---", "***"):
            out.append("<hr>"); i += 1; continue

        if ln.strip() == "":
            i += 1; continue

        buf = []                                        # paragraph
        while i < len(lines) and lines[i].strip() and not re.match(
                r"^(#|```|\||\s*[-*]\s|\d+\.\s|---$)", lines[i]):
            buf.append(lines[i].strip()); i += 1
        out.append("<p>" + inline(" ".join(buf)) + "</p>")
    return "\n".join(out)


def inline(t: str) -> str:
    t = html.escape(t)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", t)
    return t


def cards_html() -> str:
    parts = []
    for n, (title, why, cmd, then) in enumerate(CARDS, 1):
        c = ""
        if cmd:
            e = html.escape(cmd)
            c = (f'<div class="cmd"><code>{e}</code>'
                 f'<button class="cp" data-c="{e}">copy</button></div>')
        parts.append(
            f'<details class="card"><summary><span class="qn">{n}</span>'
            f'<span class="qt">{html.escape(title)}</span></summary>'
            f'<div class="cb"><p>{html.escape(why)}</p>{c}'
            f'<p class="then"><strong>Then:</strong> {html.escape(then)}</p></div></details>')
    return "\n".join(parts)


def main() -> int:
    src = HERE / "TROUBLESHOOTING.md"
    if not src.exists():
        print("render-help: TROUBLESHOOTING.md not found", file=sys.stderr)
        return 1
    page = TEMPLATE.replace("<!--CARDS-->", cards_html()) \
                   .replace("<!--PROMPT-->", html.escape(AGENT_PROMPT)) \
                   .replace("<!--GUIDE-->", md(src.read_text()))
    dest = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "help.html"
    dest.write_text(page)
    print(f"rendered {dest} ({len(page)} bytes)")
    return 0


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Something isn't working — help</title>
<style>
:root{color-scheme:dark;--bg:#0a0c0d;--panel:#101315;--panel2:#14181a;--line:#1e2427;
--tx:#c6cfd4;--hi:#f2f5f6;--dim:#8b979d;--acc:#3fd0c9;--warn:#e0a95c}
*{box-sizing:border-box}
body{margin:0;padding:28px 18px 110px;background:var(--bg);color:var(--tx);
font:16px/1.6 -apple-system,BlinkMacSystemFont,'SF Pro Text',sans-serif;
max-width:820px;margin-inline:auto;-webkit-text-size-adjust:100%}
h1{font-size:1.6rem;letter-spacing:-.02em;margin:0 0 6px;color:var(--hi)}
.lede{color:var(--dim);font-size:14.5px;margin:0 0 26px}
h2{font-size:1.06rem;color:var(--hi);margin:2.4em 0 .7em;padding-top:1.1em;border-top:1px solid var(--line)}
h3{font-size:.97rem;color:#e6ebed;margin:1.7em 0 .5em}
strong{color:var(--hi)}
a{color:var(--acc)}
code{font:12.5px/1.5 ui-monospace,'SF Mono',Menlo,monospace;background:#14181a;
color:#8fe3dd;padding:.15em .42em;border-radius:4px;word-break:break-word}
pre{background:var(--panel);border:1px solid var(--line);border-radius:9px;
padding:13px 14px;overflow-x:auto}
pre code{background:none;padding:0;color:#aebcc2;font-size:12px;white-space:pre}
table{width:100%;border-collapse:collapse;margin:1.1em 0;font-size:13.5px;display:block;overflow-x:auto}
th,td{text-align:left;padding:9px 11px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--dim);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.06em}
hr{border:0;border-top:1px solid var(--line);margin:2.2em 0}
ul,ol{padding-left:21px}li{margin:.3em 0}
.card{background:var(--panel);border:1px solid var(--line);border-radius:11px;margin-bottom:8px;overflow:hidden}
.card summary{cursor:pointer;padding:13px 15px;display:flex;gap:11px;align-items:baseline;list-style:none}
.card summary::-webkit-details-marker{display:none}
.card[open] summary{border-bottom:1px solid var(--line)}
.qn{font:600 11px ui-monospace,Menlo,monospace;color:var(--acc);flex:0 0 auto}
.qt{color:var(--hi);font-weight:550;font-size:14.5px}
.cb{padding:13px 15px}.cb p{margin:0 0 10px;font-size:14.5px}
.then{color:var(--dim);font-size:13.5px!important;margin-bottom:0!important}
.cmd{display:flex;gap:8px;align-items:flex-start;background:var(--panel2);
border:1px solid var(--line);border-radius:8px;padding:9px 11px;margin:0 0 11px}
.cmd code{flex:1;background:none;padding:0}
.cp{background:none;border:0;color:#5d686d;cursor:pointer;
font:600 10px ui-monospace,Menlo,monospace;flex:0 0 auto}
.cp:hover{color:var(--acc)}
.note{background:#141010;border:1px solid #33231b;border-left:3px solid var(--warn);
border-radius:8px;padding:13px 15px;margin:18px 0;font-size:14px;color:#c9a874}
.agent{background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:15px}
.agent pre{background:var(--panel2);margin:11px 0 0}
details.guide{margin-top:14px}
details.guide>summary{cursor:pointer;color:var(--acc);font-size:14px;padding:11px 0}
.guidebody{border-top:1px solid var(--line);margin-top:8px;padding-top:8px}
.guidebody h1{font-size:1.2rem;margin-top:1.4em}
.guidebody h2{font-size:1rem}.guidebody h3{font-size:.92rem}
footer{margin-top:38px;border-top:1px solid var(--line);padding-top:15px;color:var(--dim);font-size:13px}
</style>
</head>
<body>

<h1>Something isn't working</h1>
<p class="lede">Find what you're seeing below. Most of these need one command,
and the answer is usually in the file it produces.</p>

<div class="note"><strong>You will not break anything here.</strong> Every command
on this page only reads — none of them change, install, or delete a thing. If a
fix needs a password or a System Settings toggle, that is our job, not yours.</div>

<!--CARDS-->

<h2>Working with your AI assistant</h2>
<p>If you have Claude Code on this machine, it can diagnose and often fix this
by itself. Copy the text below into it, filling in the first line.</p>

<div class="agent">
  <button class="cp" id="cpp" style="font-size:11px">copy this prompt</button>
  <pre><code id="prompt"><!--PROMPT--></code></pre>
</div>

<p style="margin-top:16px">It will stop and ask you before anything that needs a
password or a permission dialog. Those genuinely require a person — it is not
being cautious for the sake of it.</p>

<h2>When to just call</h2>
<ul>
  <li>Anything involving a password, a payment, or a System Settings toggle</li>
  <li>Everything stopped at once, rather than one thing</li>
  <li>You have sent the doctor file and it is still not right</li>
  <li>You would rather not — that is a good enough reason</li>
</ul>

<details class="guide">
  <summary>Show the full technical guide (for an engineer or an agent)</summary>
  <div class="guidebody"><!--GUIDE--></div>
</details>

<footer>
  <p>The full guide is also <code>TROUBLESHOOTING.md</code> in the
  <code>wb-setup</code> folder on this machine. This page is generated from it,
  so the two cannot disagree.</p>
</footer>

<script>
document.addEventListener('click', function(e){
  var b = e.target.closest('.cp'); if(!b) return;
  var t = b.id === 'cpp' ? document.getElementById('prompt').textContent : b.dataset.c;
  navigator.clipboard.writeText(t);
  var o = b.textContent; b.textContent = 'copied';
  setTimeout(function(){ b.textContent = o; }, 1200);
});
</script>
</body>
</html>
"""

if __name__ == "__main__":
    sys.exit(main())
