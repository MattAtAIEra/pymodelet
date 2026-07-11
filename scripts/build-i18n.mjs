// Static i18n build for the Modelet site.
//
//   node scripts/build-i18n.mjs
//
// Reads the editable templates in site-src/ (each carries its I18N dict) and
// generates fully pre-rendered pages into docs/ — English at the root plus
// one subdirectory per language — so every language has a crawlable URL with
// baked-in text, translated <title>/<meta description>, correct lang
// attribute, canonical and hreflang links. Also emits sitemap.xml and
// robots.txt. The language switcher on generated pages navigates between
// URLs instead of swapping text in place.

import fs from 'node:fs';
import path from 'node:path';

const BASE = 'https://mattataiera.github.io/pymodelet';
const PAGES = ['index.html', 'compare-python.html'];
const LANGS = ['en', 'zh', 'ja', 'de', 'ko'];
const HTML_LANG = { en: 'en', zh: 'zh-Hant', ja: 'ja', de: 'de', ko: 'ko' };
const HREFLANG = { en: 'en', zh: 'zh-Hant', ja: 'ja', de: 'de', ko: 'ko' };

const SRC = 'site-src';
const OUT = 'docs';

function esc(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function extractDict(html, page) {
  const m = html.match(/var I18N = (\{[\s\S]*?\});\n/);
  if (!m) throw new Error('I18N dict not found in ' + page);
  return { dict: (0, eval)('(' + m[1] + ')'), raw: m[0] };
}

// Replace the text of every element bearing data-i18n / data-i18n-html.
// All such elements are leaves (no nested element of the same tag), so the
// first matching close tag after the opening tag delimits the content.
function bake(html, dict, page) {
  const re = /<([a-zA-Z0-9]+)\b[^>]*?data-i18n(-html)?="([^"]+)"[^>]*>/g;
  let out = '', last = 0, m;
  while ((m = re.exec(html)) !== null) {
    const [open, tag, isHtml, key] = [m[0], m[1], !!m[2], m[3]];
    const val = dict[key];
    if (val == null) throw new Error(`missing key ${key} in ${page}`);
    const start = m.index + open.length;
    const close = `</${tag}>`;
    const end = html.indexOf(close, start);
    if (end === -1) throw new Error(`no ${close} for ${key} in ${page}`);
    out += html.slice(last, start) + (isHtml ? val : esc(val));
    last = end;
    re.lastIndex = end + close.length;
  }
  return out + html.slice(last);
}

function urlFor(lang, page) {
  const p = page === 'index.html' ? '' : page;
  return lang === 'en' ? `${BASE}/${p}` : `${BASE}/${lang}/${p}`;
}

function headLinks(lang, page) {
  const lines = [`<link rel="canonical" href="${urlFor(lang, page)}">`];
  for (const l of LANGS)
    lines.push(`<link rel="alternate" hreflang="${HREFLANG[l]}" href="${urlFor(l, page)}">`);
  lines.push(`<link rel="alternate" hreflang="x-default" href="${urlFor('en', page)}">`);
  return lines.join('\n');
}

function runtimeScript(lang, page) {
  return `<script>
(function(){
  var PAGE='${page}', LANG='${lang}';
  var root=document.documentElement;
  var themeBtn=document.getElementById('themeBtn');
  var langSel=document.getElementById('langSel');
  var savedTheme=null; try{savedTheme=localStorage.getItem('modelet-theme')}catch(e){}
  if(savedTheme){root.setAttribute('data-theme',savedTheme)}
  function curTheme(){var t=root.getAttribute('data-theme');return t?t:(window.matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light')}
  themeBtn.addEventListener('click',function(){
    var n=curTheme()==='dark'?'light':'dark';root.setAttribute('data-theme',n);
    try{localStorage.setItem('modelet-theme',n)}catch(e){}
  });
  langSel.value=LANG;
  langSel.addEventListener('change',function(){
    var t=langSel.value;
    try{localStorage.setItem('modelet-lang',t)}catch(e){}
    if(t===LANG)return;
    var up=(LANG==='en')?'':'../';
    location.href=up+(t==='en'?'':t+'/')+PAGE;
  });
})();
</script>`;
}

fs.mkdirSync(OUT, { recursive: true });
for (const l of LANGS.filter(l => l !== 'en')) fs.mkdirSync(path.join(OUT, l), { recursive: true });

let generated = 0;
for (const page of PAGES) {
  const src = fs.readFileSync(path.join(SRC, page), 'utf8');
  const { dict: I18N } = extractDict(src, page);

  for (const lang of LANGS) {
    const dict = I18N[lang];
    let html = lang === 'en' ? src : bake(src, dict, `${page}/${lang}`);

    html = html.replace(/<html lang="[^"]*">/, `<html lang="${HTML_LANG[lang]}">`);
    html = html.replace(/<title>[\s\S]*?<\/title>/, `<title>${esc(dict['meta.title'])}</title>`);
    html = html.replace(/<meta name="description" content="[^"]*">/,
      `<meta name="description" content="${dict['meta.desc'].replace(/"/g, '&quot;')}">\n${headLinks(lang, page)}`);
    html = html.replace(/<script>\s*var I18N[\s\S]*<\/script>/, runtimeScript(lang, page));

    const dest = lang === 'en' ? path.join(OUT, page) : path.join(OUT, lang, page);
    fs.writeFileSync(dest, html);
    generated++;
  }
}

const urls = [];
for (const page of PAGES) for (const lang of LANGS) urls.push(urlFor(lang, page));
fs.writeFileSync(path.join(OUT, 'sitemap.xml'),
  `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n` +
  urls.map(u => `  <url><loc>${u}</loc></url>`).join('\n') + '\n</urlset>\n');

fs.writeFileSync(path.join(OUT, 'robots.txt'),
  `User-agent: *\nAllow: /\nSitemap: ${BASE}/sitemap.xml\n`);

fs.writeFileSync(path.join(OUT, '.nojekyll'), '');

console.log(`generated ${generated} pages + sitemap.xml + robots.txt into ${OUT}/`);
