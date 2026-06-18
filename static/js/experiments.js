// PyLab AI Experiment Lab


let EXPERIMENTS = {};


// Load experiments from JSON

fetch('/static/data/experiments.json')

  .then(r => r.json())

  .then(data => { EXPERIMENTS = data; loadExp('hello_world'); });


function loadExp(name) {
  const exp = EXPERIMENTS[name];
  if (!exp) return;

  // Update active sidebar item
  document.querySelectorAll('.exp-item').forEach(el => el.classList.remove('active'));
  const items = document.querySelectorAll('.exp-item');
  items.forEach(el => { if (el.getAttribute('onclick') === `loadExp('${name}')`) el.classList.add('active'); });

  document.getElementById('expTitle').textContent = '\u{1F9EA} ' + exp.title;
  document.getElementById('expDesc').innerHTML = '<strong>Experiment:</strong> ' + exp.desc;
  document.getElementById('expCode').value = exp.code;
  updateLineNumbers();
  clearOutput();
  addOutputLine('info', '\u{1F9EA} Loaded: ' + exp.title);
  addOutputLine('info', '\u2139\uFE0F  Press \u25B6 Run or Ctrl+Enter to execute');
  addOutputLine('normal', '\u2500'.repeat(30));
}

function updateLineNumbers() {
  const ta = document.getElementById('expCode');
  const lines = ta.value.split('\n').length;
  document.getElementById('lineNumbers').textContent = Array.from({length: lines}, (_, i) => i + 1).join('\n');
}

function addOutputLine(type, text) {
  const output = document.getElementById('outputArea');
  const div = document.createElement('div');
  div.className = 'output-line ' + type;
  div.textContent = text;
  output.appendChild(div);
  output.scrollTop = output.scrollHeight;
  document.getElementById('outputLines').textContent = output.querySelectorAll('.output-line').length + ' lines';
}

async function runExp() {
  const code = document.getElementById('expCode').value.trim();
  const stdin = document.getElementById('stdinInput').value;
  if (!code) return;

  const btn = document.getElementById('runBtn');
  const dot = document.getElementById('statusDot');
  btn.disabled = true;
  btn.innerHTML = '\u23F3 Running...';
  dot.classList.add('running');
  document.getElementById('statusText').textContent = 'Running...';

  const startTime = Date.now();
  addOutputLine('normal', '\u2500'.repeat(20) + ' ' + new Date().toLocaleTimeString() + ' ' + '\u2500'.repeat(5));

  try {
    const res = await fetch('/api/run-code', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({code, stdin})
    });
    const data = await res.json();
    const elapsed = ((Date.now() - startTime) / 1000).toFixed(2);

    if (data.output) {
      data.output.split('\n').forEach(line => addOutputLine('normal', line));
    }
    if (data.error) {
      data.error.split('\n').filter(l => l.trim()).forEach(line => addOutputLine('error', line));
    }
    if (!data.error) {
      addOutputLine('success', '\u2713 Finished in ' + elapsed + 's');
    }
    document.getElementById('execTime').textContent = 'Executed in ' + elapsed + 's';
  } catch(e) {
    addOutputLine('error', 'Connection error: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '\u25B6 Run';
    dot.classList.remove('running');
    document.getElementById('statusText').textContent = 'Ready \u2014 Ctrl+Enter to run';
  }
}

function clearExp() {
  document.getElementById('expCode').value = '';
  updateLineNumbers();
}

function clearOutput() {
  document.getElementById('outputArea').innerHTML = '';
  document.getElementById('outputLines').textContent = '0 lines';
}

function copyOutput() {
  navigator.clipboard.writeText(document.getElementById('outputArea').innerText)
    .then(() => { if(typeof showToast !== 'undefined') showToast('Copied!'); });
}

// Tab key support
document.addEventListener('DOMContentLoaded', () => {
  const ta = document.getElementById('expCode');
  if (!ta) return;

  ta.addEventListener('keydown', function(e) {
    if (e.key === 'Tab') {
      e.preventDefault();
      const s = this.selectionStart;
      this.value = this.value.substring(0, s) + '    ' + this.value.substring(this.selectionEnd);
      this.selectionStart = this.selectionEnd = s + 4;
      updateLineNumbers();
    }
    if (e.ctrlKey && e.key === 'Enter') { e.preventDefault(); runExp(); }
  });

  ta.addEventListener('input', updateLineNumbers);
  ta.addEventListener('scroll', function() {
    document.getElementById('lineNumbers').scrollTop = this.scrollTop;
  });
  ta.addEventListener('keyup', function() {
    const text = this.value.substring(0, this.selectionStart);
    const lines = text.split('\n');
    document.getElementById('cursorPos').textContent = 'Ln ' + lines.length + ', Col ' + (lines[lines.length-1].length + 1);
  });
});
