import os
import re
import json
import shutil
import subprocess
from datetime import datetime, timezone, timedelta

# ================= 配置区 =================
SUMMARY_DIR = "Summary"      # 网页简报存放的目录
INDEX_OUTPUT = "index.html"  # 日历枢纽生成位置（仓库根目录）
tz_utc_8 = timezone(timedelta(hours=8))
AUTO_PUSH_GITHUB = True      # 生成后是否自动调用 git commit & push
# ==========================================

# 注入到文章 <head> 中的批注与状态栏样式（兼容首行缩进 2em 的小说排版）
ANNO_STYLE_BLOCK = """    <style id="ss-anno-style">
        .para-wrap { margin-bottom: 1.5em; position: relative; }
        .para-wrap > p { margin-bottom: 0 !important; }
        .anno-toggle { display: inline-flex; margin-left: 6px; cursor: pointer; opacity: 0.25; font-size: 0.75em; vertical-align: middle; transition: all 0.2s; user-select: none; text-indent: 0; }
        .anno-toggle:hover { opacity: 0.85; transform: scale(1.1); }
        .anno-toggle.has-anno { opacity: 1; }
        .anno-toggle::after { content: "🔴"; }
        .anno-box { display: none; margin-top: 10px; background: #f8f6ff; border-left: 4px solid #8e7cc3; padding: 12px 16px; border-radius: 0 6px 6px 0; box-shadow: 0 2px 8px rgba(0,0,0,0.04); text-indent: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        .anno-view { font-size: 0.9em; line-height: 1.6; color: #4a4a4a; min-height: 24px; text-indent: 0; text-align: left; }
        .anno-edit { width: 100%; min-height: 110px; padding: 10px; font-family: monospace; font-size: 0.85em; border: 1px dashed #8e7cc3; border-radius: 6px; box-sizing: border-box; resize: vertical; display: none; background: #fff; color: #333; outline: none; text-indent: 0; }
        .anno-edit:focus { border: 1px solid #8e7cc3; box-shadow: 0 0 0 3px rgba(142,124,195,0.15); }
        .markdown-body p { margin-top: 0 !important; margin-bottom: 8px !important; text-indent: 0 !important; text-align: left !important; }
        .markdown-body p:last-child { margin-bottom: 0 !important; }
        .markdown-body p:empty { display: none; }
        .markdown-body h1, .markdown-body h2, .markdown-body h3 { color: #8e7cc3; font-size: 1.05em; margin: 10px 0 6px 0; border-bottom: 1px dashed #e0d8f0; padding-bottom: 4px; text-align: left !important; }
        .markdown-body ul, .markdown-body ol { margin: 0 0 8px 0; padding-left: 20px; text-indent: 0; }
        .markdown-body blockquote { margin: 0 0 10px 0; padding: 8px 14px; background: rgba(142,124,195,0.1); border-left: 4px solid #8e7cc3; color: #555; text-indent: 0; }
        .ss-nav-link { color: #b85c38; text-decoration: none; background: #faede6; padding: 2px 10px; border-radius: 6px; font-weight: 600; font-size: 0.92em; margin-left: 12px; display: inline-block; transition: background 0.2s; text-indent: 0; }
        .ss-nav-link:hover { background: #f3dccf; }
        .sync-status { position: fixed; top: 14px; right: 16px; z-index: 2000; padding: 6px 14px; border-radius: 16px; font-size: 13px; font-weight: bold; display: none; color: #fff; box-shadow: 0 3px 10px rgba(0,0,0,0.18); font-family: -apple-system, sans-serif; text-indent: 0; }
    </style>"""

# 注入到文章底部的批注交互与 GitHub 自动同步引擎（支持自动剥离运行期 .tm-word 保持源码纯净）
MATRIX_ENGINE_SCRIPT = """    <span class="sync-status" id="sync-status">📡 同步中...</span>
    <script id="matrix-engine">
        const GH_OWNER = "moodHappy";
        const GH_REPO = "ShortStories";

        function toBase64(str) {
            const bytes = new TextEncoder().encode(str);
            let bin = '';
            const chunkSize = 0x8000;
            for (let i = 0; i < bytes.length; i += chunkSize) {
                bin += String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize));
            }
            return btoa(bin);
        }

        let syncTimeout = null;
        function scheduleSync() {
            const statusMsg = document.getElementById('sync-status');
            if (!statusMsg) return;
            statusMsg.style.display = 'inline-block';
            statusMsg.style.backgroundColor = '#f39c12';
            statusMsg.innerText = '⏳ 更改已记录，5秒后自动同步...';
            statusMsg.style.cursor = 'default';
            statusMsg.onclick = null;
            if (syncTimeout) clearTimeout(syncTimeout);
            syncTimeout = setTimeout(() => { syncToGitHub(); }, 5000);
        }

        function initAnnotations() {
            document.querySelectorAll('.para-wrap').forEach(wrap => {
                const view = wrap.querySelector('.anno-view');
                const edit = wrap.querySelector('.anno-edit');
                const toggle = wrap.querySelector('.anno-toggle');
                const box = wrap.querySelector('.anno-box');
                if (!edit || !toggle || !view || !box) return;

                const rawText = edit.value.trim();
                if (rawText) {
                    toggle.classList.add('has-anno');
                    if (typeof marked !== 'undefined') { view.innerHTML = marked.parse(rawText); }
                    else { view.innerText = rawText; }
                }

                toggle.onclick = (e) => {
                    e.stopPropagation();
                    if (box.style.display === 'block') {
                        box.style.display = 'none';
                        wrap.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    } else {
                        box.style.display = 'block';
                        if (!edit.value.trim()) {
                            view.style.display = 'none';
                            edit.style.display = 'block';
                            edit.focus();
                        } else {
                            if (typeof marked !== 'undefined' && !view.innerHTML.trim()) {
                                view.innerHTML = marked.parse(edit.value.trim());
                            }
                            view.style.display = 'block';
                            edit.style.display = 'none';
                        }
                    }
                };

                const triggerEdit = () => {
                    view.style.display = 'none';
                    edit.style.display = 'block';
                    edit.focus();
                };

                // 桌面端：右键点击已渲染的批注进入编辑；双击批注收起面板
                view.addEventListener('contextmenu', e => {
                    e.preventDefault();
                    e.stopPropagation();
                    triggerEdit();
                });
                view.addEventListener('dblclick', e => {
                    e.stopPropagation();
                    box.style.display = 'none';
                    wrap.scrollIntoView({ behavior: 'smooth', block: 'center' });
                });

                // 移动端：双指轻触进入编辑；单指双击收起面板
                let lastTap = 0;
                view.addEventListener('touchstart', e => {
                    if (e.touches.length === 2) {
                        e.stopPropagation();
                        triggerEdit();
                    } else if (e.touches.length === 1) {
                        const currentTime = new Date().getTime();
                        const tapLength = currentTime - lastTap;
                        if (tapLength < 500 && tapLength > 0) {
                            e.stopPropagation();
                            box.style.display = 'none';
                            wrap.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        }
                        lastTap = currentTime;
                    }
                }, { passive: true });

                edit.onblur = () => {
                    const newVal = edit.value.trim();
                    try {
                        view.innerHTML = newVal ? (typeof marked !== 'undefined' ? marked.parse(newVal) : newVal) : '';
                    } catch (e) {}
                    edit.style.display = 'none';
                    if (newVal) {
                        view.style.display = 'block';
                        toggle.classList.add('has-anno');
                    } else {
                        view.style.display = 'none';
                        box.style.display = 'none';
                        toggle.classList.remove('has-anno');
                    }
                    if (edit.getAttribute('data-old-val') !== newVal) {
                        edit.setAttribute('data-old-val', newVal);
                        scheduleSync();
                    }
                };
                edit.setAttribute('data-old-val', rawText);
            });
        }

        function reconstructSelfHTML() {
            const clone = document.documentElement.cloneNode(true);

            // 1. 移除运行期由查词/语音生成的临时 DOM 节点
            clone.querySelectorAll('audio, [data-tippy-root], .tippy-box').forEach(el => el.remove());

            // 2. 剥离运行期包裹的 span.tm-word，还原纯文本段落，防止保存后重复包裹
            const contentContainer = clone.querySelector('#content-container');
            if (contentContainer) {
                contentContainer.style.fontSize = '';
                contentContainer.querySelectorAll('span.tm-word').forEach(span => {
                    span.replaceWith(document.createTextNode(span.textContent));
                });
                contentContainer.normalize();
            }

            // 3. 复位 body 与阅读控制栏默认状态，恢复中文段落默认模糊
            const bodyEl = clone.querySelector('body');
            if (bodyEl && contentContainer) {
                bodyEl.className = 'bar-hidden global-blur-enabled dict-enabled highlights-enabled';
            }
            const topBar = clone.querySelector('#top-bar');
            if (topBar) {
                topBar.className = 'reader-bar hidden';
            }
            clone.querySelectorAll('.zh-para').forEach(p => {
                p.classList.remove('revealed');
                if (contentContainer) p.classList.add('blurred');
            });

            // 4. 将当前页面所有批注内容写入克隆 DOM 的 textarea 中
            const liveWraps = document.querySelectorAll('.para-wrap');
            const cloneWraps = clone.querySelectorAll('.para-wrap');
            liveWraps.forEach((liveWrap, idx) => {
                const cloneWrap = cloneWraps[idx];
                if (!cloneWrap) return;
                const liveEdit = liveWrap.querySelector('.anno-edit');
                const rawVal = liveEdit ? liveEdit.value.trim() : '';

                const cloneToggle = cloneWrap.querySelector('.anno-toggle');
                const cloneBox = cloneWrap.querySelector('.anno-box');
                const cloneView = cloneWrap.querySelector('.anno-view');
                const cloneEdit = cloneWrap.querySelector('.anno-edit');

                if (cloneToggle) {
                    if (rawVal) cloneToggle.classList.add('has-anno');
                    else cloneToggle.classList.remove('has-anno');
                }
                if (cloneBox) cloneBox.style.display = 'none';
                if (cloneView) {
                    cloneView.innerHTML = '';
                    cloneView.style.display = 'none';
                }
                if (cloneEdit) {
                    cloneEdit.textContent = rawVal;
                    cloneEdit.style.display = 'none';
                    cloneEdit.removeAttribute('data-old-val');
                }
            });

            // 5. 隐藏同步状态胶囊
            const statusEl = clone.querySelector('#sync-status');
            if (statusEl) {
                statusEl.style.display = 'none';
                statusEl.innerText = '📡 同步中...';
            }

            return '<!DOCTYPE html>\\n' + clone.outerHTML;
        }

        async function syncToGitHub() {
            const token = localStorage.getItem('LITIT_GH_TOKEN') || localStorage.getItem('GH_TOKEN') || localStorage.getItem('EXT_GH_TOKEN') || localStorage.getItem('NYT_GH_TOKEN');
            if (!token) {
                alert('缺少 GitHub Token，无法同步批注！\\n\\n👉 请返回【日历中心首页】，点击右上角 ⚙️ 齿轮图标配置 Token。');
                return;
            }
            const statusMsg = document.getElementById('sync-status');
            statusMsg.style.display = 'inline-block';
            statusMsg.style.backgroundColor = '#2ea44f';
            statusMsg.innerText = '📡 同步中...';

            const pureHtml = reconstructSelfHTML();
            const decodedPath = decodeURIComponent(window.location.pathname);
            const sumIdx = decodedPath.indexOf('Summary/');
            const fileRelPath = sumIdx !== -1 ? decodedPath.substring(sumIdx) : decodedPath.replace(/^\\/+/, '');

            try {
                const base64Html = toBase64(pureHtml);
                const apiUrl = 'https://api.github.com/repos/' + GH_OWNER + '/' + GH_REPO + '/contents/' + fileRelPath;
                const getRes = await fetch(apiUrl + '?t=' + Date.now(), {
                    headers: { 'Authorization': 'Bearer ' + token },
                    cache: 'no-store'
                });
                if (!getRes.ok) throw new Error('API Rate limit or File not found: ' + fileRelPath);
                const fileData = await getRes.json();
                const putRes = await fetch(apiUrl, {
                    method: 'PUT',
                    headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: 'Auto-save annotation', content: base64Html, sha: fileData.sha })
                });
                if (putRes.ok) {
                    statusMsg.style.backgroundColor = '#2ea44f';
                    statusMsg.innerText = '✅ 云端已同步';
                    setTimeout(() => {
                        if (statusMsg.innerText === '✅ 云端已同步') statusMsg.style.display = 'none';
                    }, 3000);
                } else {
                    throw new Error('Put failed');
                }
            } catch (e) {
                console.error(e);
                statusMsg.style.backgroundColor = '#e74c3c';
                statusMsg.innerText = '❌ 同步失败 (点击重试)';
                statusMsg.style.cursor = 'pointer';
                statusMsg.onclick = () => {
                    statusMsg.onclick = null;
                    statusMsg.style.cursor = 'default';
                    syncToGitHub();
                };
            }
        }

        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', initAnnotations);
        } else {
            initAnnotations();
        }
    </script>"""


def extract_article_datetime(html_content):
    """
    同时支持两种日期格式提取：
    1. 转换器格式：发布时间：2026/10/26 13:51:14 (支持 / 或 -)
    2. 简报格式：📅 2026-09-20 20:25
    """
    match = re.search(
        r"(?:发布时间[：:]\s*|📅\s*)(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:\s+(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)?",
        html_content
    )
    if match:
        year = int(match.group(1))
        month = int(match.group(2))
        day = int(match.group(3))
        hour = int(match.group(4)) if match.group(4) is not None else 12
        minute = int(match.group(5)) if match.group(5) is not None else 0
        second = int(match.group(6)) if match.group(6) is not None else 0
        try:
            return datetime(year, month, day, hour, minute, second, tzinfo=tz_utc_8)
        except ValueError:
            pass
    return None


def adapt_article_for_shortstories(content, f_year, f_month, f_day, time_str, rel_path):
    """
    自动将转换器生成的 HTML（如 The Man Who Borrowed Time）升级为可批注、可返回对应日期日历的格式：
    1. 注入 marked.min.js 与批注样式 (#ss-anno-style)
    2. 为 #content-container 中的所有英文段落自动包裹 .para-wrap 与 🔴 批注框（自动跳过 .zh-para）
    3. 隔离 wrapTextNodesToWord 查词脚本与全局双击事件，防止破坏批注框
    4. 在『发布时间：...』旁及顶部 #top-bar 注入『🔙 返回日历』按钮，并携带 ?date=YYYY-M-D 参数
    5. 注入 #matrix-engine 自动保存批注到 ShortStories 仓库
    """
    original = content

    depth = rel_path.count("/")
    back_prefix = "../" * depth if depth > 0 else "./"
    target_back_href = f"{back_prefix}index.html?date={f_year}-{f_month}-{f_day}"

    # 1. 注入 marked.min.js
    if "marked.min.js" not in content and "</head>" in content:
        content = content.replace(
            "</head>",
            '    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>\n</head>',
            1
        )

    # 2. 注入批注 CSS 样式
    if 'id="ss-anno-style"' not in content and ".anno-toggle" not in content and "</head>" in content:
        content = content.replace("</head>", f"{ANNO_STYLE_BLOCK}\n</head>", 1)

    # 3. 为正文中所有非 .zh-para 的英文 <p> 包裹 .para-wrap 和批注框（仅处理 <script> 之前的正文区）
    if 'class="para-wrap"' not in content:
        body_script_idx = content.find("<script", content.find("<body"))
        if body_script_idx == -1:
            body_script_idx = len(content)
        head_and_body = content[:body_script_idx]
        tail_scripts = content[body_script_idx:]

        def wrap_en_p(match):
            attrs = match.group(1)
            inner = match.group(2)
            if "zh-para" in attrs or "anno-toggle" in inner:
                return match.group(0)
            return (
                '<div class="para-wrap">\n'
                f'    <p{attrs}>{inner}<span class="anno-toggle"></span></p>\n'
                '    <div class="anno-box" style="display:none;">\n'
                '        <div class="anno-view markdown-body"></div>\n'
                '        <textarea class="anno-edit" style="display:none;"></textarea>\n'
                '    </div>\n'
                '</div>'
            )

        head_and_body = re.sub(r"<p\b([^>]*)>([\s\S]*?)</p>", wrap_en_p, head_and_body)
        content = head_and_body + tail_scripts

    # 4. 隔离转换器脚本的 wrapTextNodesToWord 和 dblclick 事件，防止干扰批注框
    if "parent.closest('.zh-para')" in content and "parent.closest('.anno-box')" not in content:
        content = content.replace(
            "parent.closest('.zh-para')",
            "parent.closest('.zh-para') || parent.closest('.anno-box') || parent.closest('.anno-toggle') || parent.closest('.ss-nav-link')"
        )
    if "e.target.classList.contains('zh-para')" in content and "e.target.closest('.anno-box')" not in content:
        content = content.replace(
            "e.target.classList.contains('zh-para')",
            "e.target.classList.contains('zh-para') || e.target.closest('.anno-box') || e.target.closest('.anno-toggle')"
        )

    # 5. 在『发布时间：...』所在行注入/更新『🔙 返回日历』链接
    if "ss-nav-link" not in content:
        content = re.sub(
            r"(发布时间[：:]\s*\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:\s+\d{1,2}:\d{1,2}(?::\d{1,2})?)?)",
            rf'\1 <a href="{target_back_href}" class="ss-nav-link">🔙 返回日历</a>',
            content,
            count=1
        )
    else:
        content = re.sub(
            r'href=["\'][^"\']*index\.html(?:\?[^"\']*)?["\'](\s+class=["\']ss-nav-link["\'])',
            f'href="{target_back_href}"\\1',
            content
        )

    # 在顶部 #top-bar 控制栏中也加入『🔙 日历』按钮
    if 'class="reader-controls"' in content and "ss-top-back-btn" not in content:
        content = content.replace(
            '<div class="reader-controls">',
            f'<div class="reader-controls">\n            <button class="reader-btn ss-top-back-btn" style="background:#b85c38; color:white;" onclick="location.href=\'{target_back_href}\'">🔙 日历</button>',
            1
        )
    elif "ss-top-back-btn" in content:
        content = re.sub(
            r'onclick="location\.href=\'[^\']*index\.html(?:\?[^\']*)?\'"',
            f'onclick="location.href=\'{target_back_href}\'"',
            content
        )

    # 兼容旧版 .meta 结构的返回链接与配置
    content = re.sub(
        r'href=["\'](?:\.\./|\./)*index\.html(?:\?[^"\']*)?["\']',
        f'href="{target_back_href}"',
        content
    )
    content = re.sub(
        r'const\s+GH_REPO\s*=\s*["\'].*?["\']\s*;',
        'const GH_REPO = "ShortStories";',
        content
    )
    if "LITIT_GH_TOKEN" not in content and "localStorage.getItem('GH_TOKEN')" in content:
        content = content.replace(
            "localStorage.getItem('GH_TOKEN')",
            "localStorage.getItem('LITIT_GH_TOKEN') || localStorage.getItem('GH_TOKEN')"
        )
    old_path_snippet = "const fileRelPath = path.substring(path.indexOf('docs/'));"
    new_path_snippet = (
        "const decodedPath = decodeURIComponent(path); "
        "const sumIdx = decodedPath.indexOf('Summary/'); "
        "const fileRelPath = sumIdx !== -1 ? decodedPath.substring(sumIdx) : decodedPath.substring(decodedPath.indexOf('docs/'));"
    )
    if old_path_snippet in content:
        content = content.replace(old_path_snippet, new_path_snippet)

    # 6. 注入 #matrix-engine 批注同步脚本
    if 'id="matrix-engine"' not in content and "</body>" in content:
        content = content.replace("</body>", f"{MATRIX_ENGINE_SCRIPT}\n</body>", 1)

    return content, (content != original)


def slugify_title(title_text):
    """将标题转化为安全的文件名英文标识符"""
    clean = re.sub(r"<[^>]+>", "", title_text).strip()
    slug = re.sub(r"[^a-zA-Z0-9\s\-_]", "", clean)
    slug = re.sub(r"\s+", "-", slug.strip())
    slug = re.sub(r"-+", "-", slug).lower()
    return (slug[:50] if slug else "story").strip("-")


def scan_summary_notes():
    """扫描 Summary/ 目录及其子目录下的所有 HTML 文件，自动注入批注引擎并按文章日期构建日历索引"""
    archive_data = {}
    total_count = 0
    patched_count = 0

    if not os.path.exists(SUMMARY_DIR):
        print(f"⚠️ 找不到 '{SUMMARY_DIR}' 目录，正在自动创建...")
        os.makedirs(SUMMARY_DIR, exist_ok=True)
        return archive_data, 0

    all_html_files = []
    for root, dirs, files in os.walk(SUMMARY_DIR):
        for file_name in files:
            if file_name.endswith(".html"):
                all_html_files.append(os.path.join(root, file_name))

    for file_full_path in all_html_files:
        file_name = os.path.basename(file_full_path)

        try:
            with open(file_full_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            print(f"⚠️ 无法读取文件 {file_full_path}: {e}")
            continue

        title_match = re.search(r"<title[^>]*>(.*?)</title>", content, re.IGNORECASE | re.DOTALL)
        raw_html_title = re.sub(r"<[^>]+>", "", title_match.group(1)).strip() if title_match else ""

        match = re.search(r"^(.*)_(\d{10,13})\.html$", file_name)
        article_dt = extract_article_datetime(content)

        if match:
            raw_title = match.group(1)
            ts_ms = int(match.group(2))
            dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=tz_utc_8)
        else:
            raw_title = slugify_title(raw_html_title or file_name.replace(".html", ""))
            if article_dt:
                dt = article_dt
                ts_ms = int(dt.timestamp() * 1000)
            else:
                mtime = os.path.getmtime(file_full_path)
                ts_ms = int(mtime * 1000)
                dt = datetime.fromtimestamp(mtime, tz=tz_utc_8)

            target_dir = os.path.join(SUMMARY_DIR, str(dt.year), str(dt.month))
            os.makedirs(target_dir, exist_ok=True)
            new_file_path = os.path.join(target_dir, f"{raw_title}_{ts_ms}.html")
            if os.path.abspath(file_full_path) != os.path.abspath(new_file_path):
                shutil.move(file_full_path, new_file_path)
                file_full_path = new_file_path
                print(f"📂 已自动按文章『发布时间』归档至: {file_full_path}")

        rel_path = file_full_path.replace("\\", "/")
        f_year = str(dt.year)
        f_month = str(dt.month)
        f_day = str(dt.day)
        time_str = dt.strftime("%H:%M")

        # 🔑 自动为文章注入批注系统与返回对应日期的链接
        patched_content, is_modified = adapt_article_for_shortstories(
            content, f_year, f_month, f_day, time_str, rel_path
        )
        if is_modified:
            try:
                with open(file_full_path, "w", encoding="utf-8") as f:
                    f.write(patched_content)
                patched_count += 1
            except Exception as e:
                print(f"⚠️ 自动注入批注写入失败 {file_full_path}: {e}")

        html_title = raw_html_title if raw_html_title else raw_title
        if len(html_title) > 60:
            html_title = html_title[:60] + "..."

        display_title = f"📄 {time_str} {html_title}"

        if f_year not in archive_data:
            archive_data[f_year] = {}
        if f_month not in archive_data[f_year]:
            archive_data[f_year][f_month] = {}
        if f_day not in archive_data[f_year][f_month]:
            archive_data[f_year][f_month][f_day] = []

        archive_data[f_year][f_month][f_day].append({
            "time": time_str,
            "timestamp": ts_ms,
            "path": rel_path,
            "title": display_title,
            "rawTitle": raw_title
        })
        total_count += 1

    if patched_count > 0:
        print(f"🛠️ 已自动为 {patched_count} 篇文章注入批注引擎与日历定位链接！")

    for y in archive_data:
        for m in archive_data[y]:
            for d in archive_data[y][m]:
                archive_data[y][m][d].sort(key=lambda x: x.get("timestamp", 0), reverse=True)

    return archive_data, total_count


def generate_hub_html(archive_data):
    """生成高级文学风格的日历 WebApp (index.html)，内嵌前端自动批注注入器"""
    json_data = json.dumps(archive_data, ensure_ascii=False)
    anno_style_js_str = json.dumps(ANNO_STYLE_BLOCK, ensure_ascii=False)
    matrix_engine_js_str = json.dumps(MATRIX_ENGINE_SCRIPT, ensure_ascii=False)

    html_template = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>ShortStories - 短篇小说日历枢纽</title>
    <style>
        :root {
            --primary: #b85c38;
            --primary-gradient: linear-gradient(135deg, #c06c4b 0%, #8b4022 100%);
            --bg: #fcfbfa;
            --card: #ffffff;
            --text: #362f2d;
            --muted: #8c8279;
            --border: #e8e2da;
        }
        body, html {
            font-family: "Georgia", "Times New Roman", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, serif;
            background: var(--bg); margin: 0; padding: 0; color: var(--text); -webkit-font-smoothing: antialiased;
        }
        .container { max-width: 640px; margin: 0 auto; padding-bottom: 30px; }

        .top-bar {
            background: var(--card); padding: 14px 18px; display: flex; gap: 10px; align-items: center;
            border-bottom: 1px solid var(--border); position: sticky; top: 0; z-index: 50; box-shadow: 0 2px 10px rgba(139, 64, 34, 0.04);
        }
        .search-input {
            flex: 1; padding: 10px 16px; border: 1.5px solid var(--border); border-radius: 20px;
            font-size: 14px; outline: none; background: #fcfbfa; transition: all 0.2s; font-family: sans-serif;
        }
        .search-input:focus { border-color: var(--primary); background: #fff; box-shadow: 0 0 0 3px rgba(184, 92, 56, 0.15); }
        .settings-btn { background: none; border: none; font-size: 22px; cursor: pointer; padding: 4px; border-radius: 50%; }

        .controls {
            padding: 15px 20px; display: flex; justify-content: center; align-items: center; gap: 10px;
            background: var(--bg); border-bottom: 1px dashed var(--border);
        }
        .control-btn {
            background: var(--primary-gradient); color: #fff; border: none; border-radius: 8px;
            padding: 8px 14px; font-size: 14px; cursor: pointer; font-weight: bold; transition: all 0.2s;
            box-shadow: 0 2px 6px rgba(184, 92, 56, 0.25); font-family: sans-serif;
        }
        .control-btn:active { transform: scale(0.95); opacity: 0.9; }
        .select-box {
            padding: 6px 12px; border: 1.5px solid var(--border); border-radius: 8px;
            font-size: 15px; background: #fff; outline: none; font-weight: bold; cursor: pointer; color: var(--text);
            font-family: sans-serif;
        }

        .calendar-wrapper { background: var(--card); padding: 16px; margin-bottom: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.02); }
        .weekdays {
            display: grid; grid-template-columns: repeat(7, 1fr); text-align: center;
            font-weight: bold; font-size: 13px; color: var(--muted); margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px dashed var(--border);
            font-family: sans-serif;
        }
        .days-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 6px; font-family: sans-serif; }
        .day-cell {
            aspect-ratio: 1; display: flex; flex-direction: column; justify-content: center; align-items: center;
            font-size: 15px; font-weight: 600; border-radius: 12px; cursor: pointer; position: relative; transition: all 0.2s;
        }
        .day-cell.empty { visibility: hidden; }
        .day-cell.has-notes { color: var(--text); font-weight: 700; }
        .day-cell.no-notes { color: #d6cfc7; }
        .day-cell.selected { background: #faede6; border: 2px solid var(--primary); color: var(--primary); font-weight: bold; }
        .day-cell.today { background: #ebe3dc; color: var(--text); }
        .dot { width: 6px; height: 6px; background-color: var(--primary); border-radius: 50%; position: absolute; bottom: 6px; display: none; }
        .day-cell.has-notes .dot { display: block; }

        .notes-section { padding: 0 16px; font-family: sans-serif; }
        .note-item-wrapper { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
        .note-item {
            flex: 1; background: var(--card); border-radius: 14px; padding: 16px; display: flex;
            justify-content: space-between; align-items: center; text-decoration: none; color: var(--text);
            box-shadow: 0 2px 8px rgba(139, 64, 34, 0.05); border-left: 4px solid var(--primary); transition: all 0.2s; overflow: hidden;
        }
        .note-item:active { transform: scale(0.98); background: #faf5f2; }
        .note-title { font-size: 15px; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; text-align: left; font-weight: bold; flex: 1; }
        .delete-btn {
            background: #d9534f; color: white; border: none; border-radius: 10px; padding: 0 16px;
            height: 52px; font-size: 16px; cursor: pointer; display: none; transition: all 0.2s; flex-shrink: 0;
        }

        .empty-state { text-align: center; padding: 40px 20px; color: var(--muted); font-size: 14px; background: var(--card); border-radius: 14px; font-family: sans-serif; }
        #loadingBar { height: 3px; background: var(--primary-gradient); width: 0%; transition: width 0.3s; position: fixed; top: 0; left: 0; z-index: 9999; }

        .modal-overlay { display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(54, 47, 45, 0.6); z-index: 1000; justify-content: center; align-items: center; padding: 20px; backdrop-filter: blur(4px); font-family: sans-serif; }
        .modal-content { background: var(--card); border-radius: 16px; padding: 22px; width: 100%; max-width: 460px; box-shadow: 0 10px 30px rgba(0,0,0,0.15); max-height: 90vh; overflow-y: auto; }
        .modal-title { margin: 0 0 15px 0; font-size: 18px; font-weight: bold; color: var(--text); }
        .form-group { margin-bottom: 15px; }
        .form-group label { display: block; font-size: 13px; color: var(--muted); margin-bottom: 6px; font-weight: bold; }
        .form-group input, .form-group select, .form-group textarea { width: 100%; box-sizing: border-box; padding: 10px 12px; border: 1.5px solid var(--border); border-radius: 8px; font-size: 14px; outline: none; background: #fff; }
        .form-group input:disabled { background-color: #f5f2ef; color: #a39c97; cursor: not-allowed; }
        .form-group textarea { font-family: monospace; resize: vertical; min-height: 180px; }
        .date-hint { font-size: 12px; color: var(--primary); margin-top: 5px; display: none; font-weight: bold; }
        .modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px; border-top: 1px solid var(--border); padding-top: 12px; }
        .btn { padding: 8px 16px; border-radius: 8px; border: none; font-size: 14px; font-weight: bold; cursor: pointer; transition: opacity 0.2s; }
        .btn:hover { opacity: 0.9; }
        .btn-cancel { background: #ebe5e0; color: #5c554e; }
        .btn-save { background: var(--primary-gradient); color: #fff; }
    </style>
</head>
<body>
    <div id="loadingBar"></div>

    <div class="top-bar">
        <input type="text" id="searchInput" class="search-input" placeholder="🔍 搜索，或空置回车发布短篇小说..." autocomplete="off">
        <button class="settings-btn" id="openSettingsBtn" title="配置中心">⚙️</button>
    </div>

    <div class="container">
        <div class="controls">
            <button class="control-btn" id="prevBtn">&lt;</button>
            <select class="select-box" id="yearSelect"></select>
            <select class="select-box" id="monthSelect">
                <option value="1">01月</option><option value="2">02月</option><option value="3">03月</option>
                <option value="4">04月</option><option value="5">05月</option><option value="6">06月</option>
                <option value="7">07月</option><option value="8">08月</option><option value="9">09月</option>
                <option value="10">10月</option><option value="11">11月</option><option value="12">12月</option>
            </select>
            <button class="control-btn" id="nextBtn">&gt;</button>
            <button class="control-btn" id="todayBtn">今天</button>
        </div>

        <div class="calendar-wrapper">
            <div class="weekdays"><span>一</span><span>二</span><span>三</span><span>四</span><span>五</span><span>六</span><span>日</span></div>
            <div class="days-grid" id="daysGrid"></div>
        </div>

        <div class="notes-section">
            <div id="notesList"></div>
        </div>
    </div>

    <!-- 上传/发布 Modal -->
    <div class="modal-overlay" id="uploadModal">
        <div class="modal-content">
            <h3 class="modal-title">📤 隐秘发布终端</h3>
            <p style="font-size:12px; color:#888; margin-top:-10px; margin-bottom:15px;">直接粘贴转换工具生成的 HTML，系统将自动提取『发布时间』、注入 🔴 段落批注引擎并推送至对应日期。</p>
            
            <div class="form-group">
                <label>英文标识符 (自动从源码 &lt;title&gt; 提取)</label>
                <input type="text" id="upFilename" placeholder="粘贴下方源码后自动生成...">
            </div>
            <div class="form-group">
                <label>归档日期与时间 (自动识别『发布时间』或跟随当前选中日历)</label>
                <input type="datetime-local" id="upDateTime" step="1">
                <div class="date-hint" id="dateHint">✨ 已自动识别并匹配文章内的发布时间！</div>
            </div>
            <div class="form-group">
                <label>短篇小说 HTML 源码</label>
                <textarea id="upContent" placeholder="在此粘贴转换工具生成的完整 HTML 代码..."></textarea>
            </div>

            <div class="modal-actions">
                <button class="btn btn-cancel" id="closeUploadBtn">取消</button>
                <button class="btn btn-save" id="saveUploadBtn">推送至云端 🚀</button>
            </div>
        </div>
    </div>

    <!-- 设置 Modal -->
    <div class="modal-overlay" id="settingsModal">
        <div class="modal-content">
            <h3 class="modal-title">⚙️ 核心配置中心</h3>
            <p style="font-size:12px; color:#888; margin-top:-10px; margin-bottom:15px;">设置后在阅读页面中点击 🔴 添加批注即可自动同步保存至 GitHub。</p>
            
            <div class="form-group">
                <label>GitHub Personal Token</label>
                <input type="password" id="cfgGhToken" placeholder="ghp_xxxxxxxxxxxxxxxxxxxx">
            </div>
            <div class="form-group" style="display:flex; gap:10px;">
                <div style="flex:1;">
                    <label>GitHub 用户名 (已锁定)</label>
                    <input type="text" value="moodHappy" disabled>
                </div>
                <div style="flex:1;">
                    <label>GitHub 仓库名 (已锁定)</label>
                    <input type="text" value="ShortStories" disabled>
                </div>
            </div>

            <div style="border-top: 1px dashed var(--border); margin: 15px 0;"></div>

            <div class="form-group">
                <label>自定义 AI Endpoint URL</label>
                <input type="text" id="cfgCustomUrl" placeholder="如: https://api.chatanywhere.tech/v1/chat/completions">
            </div>
            <div class="form-group" style="display:flex; gap:10px;">
                <div style="flex:1;">
                    <label>API Key</label>
                    <input type="password" id="cfgCustomKey" placeholder="sk-xxxxxx">
                </div>
                <div style="flex:1;">
                    <label>模型名称</label>
                    <input type="text" id="cfgCustomModel" placeholder="gpt-4.1">
                </div>
            </div>

            <div class="modal-actions">
                <button class="btn btn-cancel" id="closeSettingsBtn">取消</button>
                <button class="btn btn-save" id="saveSettingsBtn">保存本地配置</button>
            </div>
        </div>
    </div>

    <script>
        const archiveData = /*DATA_START*/REPLACEME_JSON_DATA/*DATA_END*/;
        const ANNO_STYLE_TEMPLATE = __ANNO_STYLE_PLACEHOLDER__;
        const MATRIX_ENGINE_TEMPLATE = __MATRIX_ENGINE_PLACEHOLDER__;
        const today = new Date();
        
        // 🔒 锁死配置
        const GH_OWNER = 'moodHappy';
        const GH_REPO = 'ShortStories';
        
        const AppState = {
            year: today.getFullYear(),
            month: today.getMonth() + 1,
            day: today.getDate(),
            deleteMode: false,
            filterText: ''
        };

        // 🔑 支持从文章内点击『🔙 返回日历』时通过 ?date=YYYY-M-D 精准跳回文章所属日期
        (function applyUrlDateParam() {
            const params = new URLSearchParams(window.location.search);
            const dateStr = params.get('date');
            if (dateStr) {
                const parts = dateStr.split('-').map(Number);
                if (parts.length === 3 && !isNaN(parts[0]) && !isNaN(parts[1]) && !isNaN(parts[2])) {
                    AppState.year = parts[0];
                    AppState.month = parts[1];
                    AppState.day = parts[2];
                }
            }
        })();

        function pad2(n) { return String(n).padStart(2, '0'); }

        function getSelectedDateTimeLocalStr() {
            const now = new Date();
            return `${AppState.year}-${pad2(AppState.month)}-${pad2(AppState.day)}T${pad2(now.getHours())}:${pad2(now.getMinutes())}:${pad2(now.getSeconds())}`;
        }

        // 🚀 浏览器端自动注入引擎：将转换工具生成的 HTML 自动植入 🔴 批注系统、防冲突过滤与日历返回链接
        function adaptHtmlForShortStories(rawHtml, yearStr, monthStr, dayStr) {
            let html = rawHtml;
            const targetBackHref = `../../../index.html?date=${yearStr}-${monthStr}-${dayStr}`;

            // 1. 注入 marked.min.js
            if (!html.includes('marked.min.js') && html.includes('</head>')) {
                html = html.replace('</head>', '    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"><\/script>\n</head>');
            }

            // 2. 注入批注 CSS
            if (!html.includes('id="ss-anno-style"') && !html.includes('.anno-toggle') && html.includes('</head>')) {
                html = html.replace('</head>', ANNO_STYLE_TEMPLATE + '\n</head>');
            }

            // 3. 为正文中所有英文 <p> 段落包裹 .para-wrap 与 🔴 批注框（自动跳过 .zh-para）
            if (!html.includes('class="para-wrap"')) {
                const bodyIdx = html.indexOf('<body');
                let scriptIdx = bodyIdx !== -1 ? html.indexOf('<script', bodyIdx) : -1;
                if (scriptIdx === -1) scriptIdx = html.length;

                let beforeScript = html.substring(0, scriptIdx);
                const afterScript = html.substring(scriptIdx);

                beforeScript = beforeScript.replace(/<p\b([^>]*)>([\s\S]*?)<\/p>/gi, function(fullMatch, attrs, inner) {
                    if (attrs.includes('zh-para') || inner.includes('anno-toggle')) return fullMatch;
                    return '<div class="para-wrap">\n' +
                        '    <p' + attrs + '>' + inner + '<span class="anno-toggle"></span></p>\n' +
                        '    <div class="anno-box" style="display:none;">\n' +
                        '        <div class="anno-view markdown-body"></div>\n' +
                        '        <textarea class="anno-edit" style="display:none;"></textarea>\n' +
                        '    </div>\n' +
                        '</div>';
                });
                html = beforeScript + afterScript;
            }

            // 4. 隔离 wrapTextNodesToWord 查词包裹与全局双击顶栏事件，防止干扰批注框
            if (html.includes("parent.closest('.zh-para')") && !html.includes("parent.closest('.anno-box')")) {
                html = html.replace(
                    "parent.closest('.zh-para')",
                    "parent.closest('.zh-para') || parent.closest('.anno-box') || parent.closest('.anno-toggle') || parent.closest('.ss-nav-link')"
                );
            }
            if (html.includes("e.target.classList.contains('zh-para')") && !html.includes("e.target.closest('.anno-box')")) {
                html = html.replace(
                    "e.target.classList.contains('zh-para')",
                    "e.target.classList.contains('zh-para') || e.target.closest('.anno-box') || e.target.closest('.anno-toggle')"
                );
            }

            // 5. 在『发布时间：...』旁及顶部 #top-bar 注入『🔙 返回日历』按钮
            if (!html.includes('ss-nav-link')) {
                html = html.replace(
                    /(发布时间[：:]\s*\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:\s+\d{1,2}:\d{1,2}(?::\d{1,2})?)?)/,
                    `$1 <a href="${targetBackHref}" class="ss-nav-link">🔙 返回日历</a>`
                );
            } else {
                html = html.replace(
                    /href=["'][^"']*index\.html(?:\?[^"']*)?["'](\s+class=["']ss-nav-link["'])/g,
                    `href="${targetBackHref}"$1`
                );
            }

            if (html.includes('class="reader-controls"') && !html.includes('ss-top-back-btn')) {
                html = html.replace(
                    '<div class="reader-controls">',
                    `<div class="reader-controls">\n            <button class="reader-btn ss-top-back-btn" style="background:#b85c38; color:white;" onclick="location.href='${targetBackHref}'">🔙 日历</button>`
                );
            }

            // 兼容旧版 .meta 模板
            html = html.replace(/href=["'](?:\.\.\/|\.\/)*index\.html(?:\?[^"']*)?["']/g, `href="${targetBackHref}"`);
            html = html.replace(/const\s+GH_REPO\s*=\s*["'].*?["']\s*;/g, 'const GH_REPO = "ShortStories";');

            // 6. 注入 #matrix-engine 批注同步引擎
            if (!html.includes('id="matrix-engine"') && html.includes('</body>')) {
                html = html.replace('</body>', MATRIX_ENGINE_TEMPLATE + '\n</body>');
            }

            return html;
        }

        function initSelects() {
            const yearSelect = document.getElementById('yearSelect');
            yearSelect.innerHTML = '';
            const currentYear = today.getFullYear();
            const allYears = new Set(Object.keys(archiveData).map(Number));
            
            for (let y = currentYear - 5; y <= currentYear + 50; y++) {
                allYears.add(y);
            }
            
            Array.from(allYears).sort((a, b) => b - a).forEach(y => { 
                const opt = document.createElement('option'); 
                opt.value = y; opt.textContent = y + ' 年'; yearSelect.appendChild(opt); 
            });
        }

        function forceRender() {
            const maxDay = new Date(AppState.year, AppState.month, 0).getDate();
            if (AppState.day > maxDay) AppState.day = maxDay;

            document.getElementById('yearSelect').value = AppState.year;
            document.getElementById('monthSelect').value = AppState.month;

            const daysGrid = document.getElementById('daysGrid');
            const notesList = document.getElementById('notesList');

            daysGrid.innerHTML = ''; notesList.innerHTML = '';

            try {
                const firstDay = new Date(AppState.year, AppState.month - 1, 1).getDay() || 7;
                for (let i = 1; i < firstDay; i++) { 
                    const emptyCell = document.createElement('div'); 
                    emptyCell.className = 'day-cell empty'; daysGrid.appendChild(emptyCell); 
                }
                
                const monthData = (archiveData[AppState.year] && archiveData[AppState.year][AppState.month]) || {};
                
                for (let day = 1; day <= maxDay; day++) {
                    const cell = document.createElement('div'); cell.className = 'day-cell'; cell.textContent = day;
                    const dot = document.createElement('div'); dot.className = 'dot'; cell.appendChild(dot);
                    
                    if (monthData[day] && monthData[day].length > 0) cell.classList.add('has-notes'); else cell.classList.add('no-notes');
                    if (AppState.year === today.getFullYear() && AppState.month === today.getMonth() + 1 && day === today.getDate()) cell.classList.add('today');
                    if (day === AppState.day) cell.classList.add('selected');
                    
                    cell.onclick = () => { AppState.day = day; forceRender(); };
                    daysGrid.appendChild(cell);
                }
            } catch (err) { console.error(err); }

            try {
                let dayData = null;
                if (archiveData[AppState.year] && archiveData[AppState.year][AppState.month] && archiveData[AppState.year][AppState.month][AppState.day]) {
                    dayData = archiveData[AppState.year][AppState.month][AppState.day];
                }
                
                if (dayData && Array.isArray(dayData) && dayData.length > 0) {
                    dayData.sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0));

                    let filtered = dayData;
                    if (AppState.filterText) {
                        filtered = dayData.filter(item => item.title.toLowerCase().includes(AppState.filterText.toLowerCase()));
                    }

                    if (filtered.length > 0) {
                        filtered.forEach((note, index) => {
                            const wrapper = document.createElement('div'); wrapper.className = 'note-item-wrapper';
                            const a = document.createElement('a'); a.href = note.path; a.className = 'note-item';
                            a.innerHTML = `<span class="note-title">${note.title}</span>`;
                            wrapper.appendChild(a);

                            const delBtn = document.createElement('button'); delBtn.className = 'delete-btn'; delBtn.innerHTML = '🗑️';
                            if (AppState.deleteMode) delBtn.style.display = 'block';
                            
                            delBtn.onclick = async (e) => {
                                e.preventDefault();
                                if(confirm('确认删除此篇小说并同步删除 GitHub 云端文件吗？')) {
                                    const pathToDelete = note.path;
                                    dayData.splice(index, 1);
                                    if (dayData.length === 0) delete archiveData[AppState.year][AppState.month][AppState.day];
                                    forceRender();
                                    await syncDeleteToGithub(pathToDelete);
                                }
                            };
                            wrapper.appendChild(delBtn); notesList.appendChild(wrapper);
                        });
                    } else {
                        notesList.innerHTML = '<div class="empty-state">未找到匹配的小说 🔍</div>';
                    }
                } else {
                    notesList.innerHTML = '<div class="empty-state">当日暂无短篇小说 📖</div>';
                }
            } catch (err) { console.error(err); }
        }

        document.getElementById('yearSelect').addEventListener('change', (e) => { AppState.year = parseInt(e.target.value, 10); forceRender(); });
        document.getElementById('monthSelect').addEventListener('change', (e) => { AppState.month = parseInt(e.target.value, 10); forceRender(); });
        document.getElementById('prevBtn').addEventListener('click', () => { AppState.month--; if (AppState.month < 1) { AppState.month = 12; AppState.year--; } forceRender(); });
        document.getElementById('nextBtn').addEventListener('click', () => { AppState.month++; if (AppState.month > 12) { AppState.month = 1; AppState.year++; } forceRender(); });
        document.getElementById('todayBtn').addEventListener('click', () => { AppState.year = today.getFullYear(); AppState.month = today.getMonth() + 1; AppState.day = today.getDate(); forceRender(); });

        document.getElementById('searchInput').addEventListener('input', (e) => {
            AppState.filterText = e.target.value.trim();
            forceRender();
        });
        
        document.getElementById('searchInput').addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && e.target.value.trim() === '') {
                e.preventDefault();
                document.getElementById('upFilename').value = '';
                document.getElementById('upContent').value = '';
                document.getElementById('upDateTime').value = getSelectedDateTimeLocalStr();
                document.getElementById('dateHint').style.display = 'none';
                document.getElementById('uploadModal').style.display = 'flex';
                setTimeout(() => { document.getElementById('upContent').focus(); }, 100);
            }
        });

        let lastTap = 0;
        document.querySelector('.calendar-wrapper').addEventListener('click', (e) => {
            const tapLength = new Date().getTime() - lastTap;
            if (tapLength < 500 && tapLength > 0) {
                AppState.deleteMode = !AppState.deleteMode;
                document.querySelectorAll('.delete-btn').forEach(btn => btn.style.display = AppState.deleteMode ? 'block' : 'none');
                e.preventDefault();
            }
            lastTap = new Date().getTime();
        });

        initSelects(); forceRender();

        /* ================= 核心发布功能 ================= */
        document.getElementById('closeUploadBtn').addEventListener('click', () => { document.getElementById('uploadModal').style.display = 'none'; });
        
        // 🚀 粘贴源码后自动提取 <title> 及『发布时间：2026/10/26 13:51:14』
        document.getElementById('upContent').addEventListener('input', (e) => {
            const content = e.target.value;
            const titleMatch = content.match(/<title[^>]*>(.*?)<\/title>/i);
            
            if (titleMatch && titleMatch[1]) {
                let rawTitle = titleMatch[1].replace(/<[^>]+>/g, '').trim();
                let autoFilename = rawTitle
                    .replace(/[^a-zA-Z0-9\s-_]/g, '')
                    .replace(/\s+/g, '-')
                    .replace(/-+/g, '-')
                    .toLowerCase();
                
                if (autoFilename.length > 50) {
                    autoFilename = autoFilename.substring(0, 50);
                }
                document.getElementById('upFilename').value = autoFilename.replace(/^-+|-+$/g, '');
            } else {
                document.getElementById('upFilename').value = '';
            }

            // 匹配『发布时间：2026/10/26 13:51:14』或『📅 2026-09-20 20:25』
            const dateMatch = content.match(/(?:发布时间[：:]\s*|📅\s*)(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:\s+(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)?/);
            const dateHint = document.getElementById('dateHint');
            if (dateMatch) {
                const y = dateMatch[1];
                const m = pad2(dateMatch[2]);
                const d = pad2(dateMatch[3]);
                const hh = dateMatch[4] !== undefined ? pad2(dateMatch[4]) : '12';
                const mm = dateMatch[5] !== undefined ? pad2(dateMatch[5]) : '00';
                const ss = dateMatch[6] !== undefined ? pad2(dateMatch[6]) : '00';
                document.getElementById('upDateTime').value = `${y}-${m}-${d}T${hh}:${mm}:${ss}`;
                dateHint.innerText = `✨ 已自动识别文章发布时间：${y}-${m}-${d} ${hh}:${mm}:${ss}`;
                dateHint.style.display = 'block';
            } else {
                dateHint.style.display = 'none';
            }
        });

        document.getElementById('saveUploadBtn').addEventListener('click', async () => {
            let filename = document.getElementById('upFilename').value.trim();
            let rawContent = document.getElementById('upContent').value.trim();
            
            if(!rawContent) return alert("请粘贴 HTML 代码！");
            
            filename = filename.replace(/[^a-zA-Z0-9\s-_]/g, '').trim().replace(/\s+/g, '-').replace(/^-+|-+$/g, '');
            if(!filename) filename = "story";

            const ghToken = localStorage.getItem('LITIT_GH_TOKEN') || localStorage.getItem('GH_TOKEN');
            if (!ghToken) return alert('请先通过右侧齿轮 ⚙️ 配置 GitHub Token！');

            const dtVal = document.getElementById('upDateTime').value;
            const targetDate = dtVal ? new Date(dtVal) : new Date(AppState.year, AppState.month - 1, AppState.day, new Date().getHours(), new Date().getMinutes());
            
            const yearStr = String(targetDate.getFullYear());
            const monthStr = String(targetDate.getMonth() + 1);
            const dayStr = String(targetDate.getDate());
            const timeStr = pad2(targetDate.getHours()) + ':' + pad2(targetDate.getMinutes());
            const ts = targetDate.getTime();
            
            // 🔑 自动将转换器生成的 HTML 升级为带 🔴 批注与日历返回链接的格式
            const adaptedContent = adaptHtmlForShortStories(rawContent, yearStr, monthStr, dayStr);

            const fullPath = `Summary/${yearStr}/${monthStr}/${filename}_${ts}.html`;
            
            try {
                const loadingBar = document.getElementById('loadingBar');
                loadingBar.style.width = '20%';
                document.getElementById('saveUploadBtn').innerText = "推送中...";
                
                // 1. 推送注入批注后的 HTML 文件到仓库
                const base64Content = btoa(unescape(encodeURIComponent(adaptedContent)));
                const resUpload = await fetch(`https://api.github.com/repos/${GH_OWNER}/${GH_REPO}/contents/${fullPath}`, {
                    method: 'PUT',
                    headers: { 'Authorization': `Bearer ${ghToken}`, 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: `Upload short story (${yearStr}-${monthStr}-${dayStr}): ${filename}`, content: base64Content })
                });

                if(!resUpload.ok) throw new Error("文件推送失败");
                loadingBar.style.width = '60%';

                // 2. 提取 <title> 更新索引
                let displayTitleMatch = adaptedContent.match(/<title[^>]*>(.*?)<\/title>/i);
                let htmlTitle = displayTitleMatch ? displayTitleMatch[1].replace(/<[^>]+>/g, '').trim() : "未命名小说";
                
                if (htmlTitle.length > 60) {
                    htmlTitle = htmlTitle.substring(0, 60) + "...";
                }

                if(!archiveData[yearStr]) archiveData[yearStr] = {};
                if(!archiveData[yearStr][monthStr]) archiveData[yearStr][monthStr] = {};
                if(!archiveData[yearStr][monthStr][dayStr]) archiveData[yearStr][monthStr][dayStr] = [];

                archiveData[yearStr][monthStr][dayStr].push({
                    time: timeStr,
                    timestamp: ts,
                    path: fullPath,
                    title: `📄 ${timeStr} ${htmlTitle}`,
                    rawTitle: filename
                });

                // 跳转日历到文章所属的日期并重绘
                AppState.year = targetDate.getFullYear();
                AppState.month = targetDate.getMonth() + 1;
                AppState.day = targetDate.getDate();
                initSelects();
                forceRender();

                // 3. 同步更新云端 index.html
                const idxRes = await fetch(`https://api.github.com/repos/${GH_OWNER}/${GH_REPO}/contents/index.html`, { headers: { 'Authorization': `Bearer ${ghToken}` } });
                const idxData = await idxRes.json();
                const idxContent = decodeURIComponent(escape(atob(idxData.content.replace(/\s/g, ''))));
                
                const dataStart = idxContent.indexOf('/*DATA_START*/') + 14;
                const dataEnd = idxContent.indexOf('/*DATA_END*/');
                const newIdxContent = idxContent.substring(0, dataStart) + JSON.stringify(archiveData) + idxContent.substring(dataEnd);
                
                loadingBar.style.width = '85%';
                await fetch(`https://api.github.com/repos/${GH_OWNER}/${GH_REPO}/contents/index.html`, { 
                    method: 'PUT', 
                    headers: { 'Authorization': `Bearer ${ghToken}`, 'Content-Type': 'application/json' }, 
                    body: JSON.stringify({ message: `Auto-update index.html after upload`, content: btoa(unescape(encodeURIComponent(newIdxContent))), sha: idxData.sha }) 
                });

                loadingBar.style.width = '100%';
                setTimeout(() => { loadingBar.style.width = '0%'; }, 1000);
                
                document.getElementById('uploadModal').style.display = 'none';
                document.getElementById('saveUploadBtn').innerText = "推送至云端 🚀";
                alert(`🎉 发布成功！已自动注入 🔴 批注系统并归档至 ${yearStr}-${pad2(monthStr)}-${pad2(dayStr)}。`);
                
            } catch (e) {
                console.error(e);
                alert("上传失败: " + e.message);
                document.getElementById('loadingBar').style.width = '0%';
                document.getElementById('saveUploadBtn').innerText = "推送至云端 🚀";
            }
        });

        /* ================= 核心设置/删除功能 ================= */
        document.getElementById('openSettingsBtn').addEventListener('click', () => {
            document.getElementById('cfgGhToken').value = localStorage.getItem('LITIT_GH_TOKEN') || localStorage.getItem('GH_TOKEN') || '';
            document.getElementById('cfgCustomUrl').value = localStorage.getItem('LITIT_CUSTOM_API_URL') || '';
            document.getElementById('cfgCustomKey').value = localStorage.getItem('LITIT_CUSTOM_API_KEY') || '';
            document.getElementById('cfgCustomModel').value = localStorage.getItem('LITIT_CUSTOM_MODEL') || '';
            document.getElementById('settingsModal').style.display = 'flex';
        });
        
        document.getElementById('closeSettingsBtn').addEventListener('click', () => { document.getElementById('settingsModal').style.display = 'none'; });
        
        document.getElementById('saveSettingsBtn').addEventListener('click', () => {
            const tokenVal = document.getElementById('cfgGhToken').value.trim();
            localStorage.setItem('LITIT_GH_TOKEN', tokenVal);
            if (tokenVal) localStorage.setItem('GH_TOKEN', tokenVal);
            localStorage.setItem('LITIT_CUSTOM_API_URL', document.getElementById('cfgCustomUrl').value.trim());
            localStorage.setItem('LITIT_CUSTOM_API_KEY', document.getElementById('cfgCustomKey').value.trim());
            localStorage.setItem('LITIT_CUSTOM_MODEL', document.getElementById('cfgCustomModel').value.trim());
            document.getElementById('settingsModal').style.display = 'none';
            alert('配置已保存在本地浏览器！');
        });

        async function syncDeleteToGithub(fileRelPath) {
            const ghToken = localStorage.getItem('LITIT_GH_TOKEN') || localStorage.getItem('GH_TOKEN');
            
            if (!ghToken) return alert('本地已移出索引，但未配置 GitHub Token，远端文件未删除。');
            try {
                const loadingBar = document.getElementById('loadingBar'); loadingBar.style.width = '30%';
                const fileRes = await fetch(`https://api.github.com/repos/${GH_OWNER}/${GH_REPO}/contents/${fileRelPath}`, { headers: { 'Authorization': `Bearer ${ghToken}` } });
                if (fileRes.ok) {
                    const fileData = await fileRes.json();
                    await fetch(`https://api.github.com/repos/${GH_OWNER}/${GH_REPO}/contents/${fileRelPath}`, { method: 'DELETE', headers: { 'Authorization': `Bearer ${ghToken}`, 'Content-Type': 'application/json' }, body: JSON.stringify({ message: `Delete note: ${fileRelPath}`, sha: fileData.sha }) });
                }
                loadingBar.style.width = '70%';
                const idxRes = await fetch(`https://api.github.com/repos/${GH_OWNER}/${GH_REPO}/contents/index.html`, { headers: { 'Authorization': `Bearer ${ghToken}` } });
                const idxData = await idxRes.json();
                const idxContent = decodeURIComponent(escape(atob(idxData.content.replace(/\s/g, ''))));
                
                const dataStart = idxContent.indexOf('/*DATA_START*/') + 14;
                const dataEnd = idxContent.indexOf('/*DATA_END*/');
                const newIdxContent = idxContent.substring(0, dataStart) + JSON.stringify(archiveData) + idxContent.substring(dataEnd);
                
                loadingBar.style.width = '90%';
                await fetch(`https://api.github.com/repos/${GH_OWNER}/${GH_REPO}/contents/index.html`, { method: 'PUT', headers: { 'Authorization': `Bearer ${ghToken}`, 'Content-Type': 'application/json' }, body: JSON.stringify({ message: `Update index.html after deletion`, content: btoa(unescape(encodeURIComponent(newIdxContent))), sha: idxData.sha }) });
                loadingBar.style.width = '100%'; setTimeout(() => { loadingBar.style.width = '0%'; }, 1000);
            } catch(e) { console.error(e); alert('云端同步删除失败: ' + e.message); document.getElementById('loadingBar').style.width = '0%'; }
        }
    </script>
</body>
</html>"""

    html_template = html_template.replace("REPLACEME_JSON_DATA", json_data)
    html_template = html_template.replace("__ANNO_STYLE_PLACEHOLDER__", anno_style_js_str)
    html_template = html_template.replace("__MATRIX_ENGINE_PLACEHOLDER__", matrix_engine_js_str)

    with open(INDEX_OUTPUT, "w", encoding="utf-8") as f:
        f.write(html_template)
    print(f"🚀 成功生成日历枢纽 WebApp: {INDEX_OUTPUT}")


def git_push_to_github():
    """自动提交变更并推送到 GitHub 仓库"""
    if os.getenv("GITHUB_ACTIONS") == "true":
        print("ℹ️ 当前处于 GitHub Actions 云端环境，交由 Workflow 执行 Commit & Push。")
        return

    if not AUTO_PUSH_GITHUB:
        return

    print("\n⏳ 正在自动推送变更到 GitHub...")
    if not os.path.exists(".git"):
        print("⚠️ 当前目录并非 Git 仓库，跳过 Git Push。")
        return
    try:
        subprocess.run(["git", "add", "."], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        if not status.stdout.strip():
            print("ℹ️ 没有发现需要推播的更新。")
            return

        subprocess.run(["git", "commit", "-m", "Auto-update ShortStories calendar index & inject annotation engine"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["git", "push"], check=True)
        print("✅ 成功同步推送到 GitHub！网页版日历约在 1 分钟后更新可见。")
    except subprocess.CalledProcessError as e:
        print(f"❌ Git 执行失败，错误码: {e.returncode}")


def main():
    print("=======================================")
    print("📚 ShortStories - 故事日历枢纽生成器")
    print("=======================================")
    archive_data, count = scan_summary_notes()
    print(f"🔍 扫描完成，共找到 {count} 篇短篇小说。")
    generate_hub_html(archive_data)
    git_push_to_github()


if __name__ == "__main__":
    main()
