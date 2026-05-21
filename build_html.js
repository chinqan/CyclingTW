const fs = require('fs');
const path = require('path');
const { marked } = require('marked');

// Custom renderer to handle some specific markdown formatting or we can just replace string after.
const indexMdPath = path.join(__dirname, 'index.md');
const outputHtmlPath = path.join(__dirname, 'index.html');

function preserveMermaidBlocks(markdown) {
    const blocks = [];
    const replacedMarkdown = markdown.replace(/```mermaid\r?\n([\s\S]*?)\r?\n```/g, (match, mermaidSource) => {
        const placeholder = `@@MERMAID_BLOCK_${blocks.length}@@`;
        blocks.push(mermaidSource);
        return placeholder;
    });

    return { markdown: replacedMarkdown, blocks };
}

function restoreMermaidBlocks(html, blocks) {
    return html.replace(/<p>@@MERMAID_BLOCK_(\d+)@@<\/p>/g, (match, index) => {
        const mermaidSource = blocks[Number(index)];
        return `<div class="mermaid">\n${mermaidSource}\n</div>`;
    });
}

function emphasizeBlueWords(markdown) {
    let updatedMarkdown = markdown;

    blueWords.forEach(word => {
        // The mermaid blocks are extracted before this runs, so these spans only affect regular markdown.
        const regex = new RegExp(word, 'g');
        updatedMarkdown = updatedMarkdown.replace(regex, `<span class="blue-text">${word}</span>`);
    });

    return updatedMarkdown;
}

function removePromptCompositionGuide(markdown) {
    return markdown.replace(/^##\s+.*提示詞構圖指引[\s\S]*$/m, '').trimEnd();
}

function layoutDayIntro(html) {
    return html.replace(
        /(<h2>[^<]*路線總覽<\/h2>[\s\S]*?)(<h4>[^<]*路線小地圖<\/h4>[\s\S]*?)(<hr>\s*<h2>[^<]*詳細路線行程圖解<\/h2>)/,
        `<div class="day-intro-grid">
            <div class="day-intro-summary">
                $1
            </div>
            <div class="day-intro-map">
                $2
            </div>
        </div>
        $3`
    );
}

function renderMapReminders(html) {
    return html.replace(/\n> 💡 \*(.*?)\*/g, '\n<blockquote><p><em>💡 $1</em></p></blockquote>');
}


let indexContent = fs.readFileSync(indexMdPath, 'utf-8');

// Replace day links in index.md to anchor links and prevent wrap
indexContent = indexContent.replace(/\[Day (\d+)\]\(\.\/day\d+\/day\d+\.md\)/g, '<a href="#day$1" class="nowrap">Day $1</a>');

// Replace "四極點" and the four specific points with blue text
const blueWords = [
    '四極點',
    '極西：國聖燈塔',
    '極南：鵝鑾鼻燈塔',
    '極東：三貂角燈塔',
    '極北：富貴角燈塔',
    '極西點國聖燈塔'
];

indexContent = emphasizeBlueWords(indexContent);

let mainHtml = marked.parse(indexContent);

let daysHtml = '';
for (let i = 1; i <= 10; i++) {
    const dayMdPath = path.join(__dirname, `day${i}`, `day${i}.md`);
    if (fs.existsSync(dayMdPath)) {
        let dayContent = fs.readFileSync(dayMdPath, 'utf-8');
        dayContent = removePromptCompositionGuide(dayContent);
        const mermaidPreserved = preserveMermaidBlocks(dayContent);
        dayContent = mermaidPreserved.markdown;
        dayContent = emphasizeBlueWords(dayContent);
        
        // Rename '魚骨圖' to '詳細路線行程圖解'
        dayContent = dayContent.replace(/魚骨圖 \(Ishikawa Diagram\)/g, '詳細路線行程圖解');
        dayContent = dayContent.replace(/Day (\d+) 路線魚骨圖/g, 'Day $1 詳細路線行程圖解');
        
        let dayHtmlParsed = marked.parse(dayContent);
        dayHtmlParsed = restoreMermaidBlocks(dayHtmlParsed, mermaidPreserved.blocks);
        
        // Fix image paths (relative to the day directory, now from root)
        dayHtmlParsed = dayHtmlParsed.replace(/src="\.\//g, `src="./day${i}/`);
        dayHtmlParsed = dayHtmlParsed.replace(/href="\.\//g, `href="./day${i}/`);
        dayHtmlParsed = renderMapReminders(dayHtmlParsed);
        dayHtmlParsed = layoutDayIntro(dayHtmlParsed);

        daysHtml += `
        <div id="day${i}" class="day-section">
            <div class="day-content">
                ${dayHtmlParsed}
            </div>
            <a href="#" class="back-to-top">↑ 回到總覽表</a>
        </div>
        <hr>
        `;
    }
}

const finalHtml = `<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>10天單車環島計畫 (四極點)</title>
    <style>
        body {
            font-family: "Helvetica Neue", Helvetica, Arial, "PingFang TC", "Heiti TC", "Microsoft JhengHei", sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 1000px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f9f9f9;
        }
        h1, h2, h3, h4 {
            color: #2c3e50;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 30px;
            background-color: #fff;
            box-shadow: 0 2px 5px rgba(0,0,0,0.05);
        }
        th, td {
            border: 1px solid #ddd;
            padding: 12px;
            text-align: left;
        }
        th {
            background-color: #f2f2f2;
        }
        /* Day 1 等字樣不要被斷行 */
        .nowrap {
            white-space: nowrap;
        }
        /* 四極點藍色字體標示 */
        .blue-text {
            color: #0066cc;
            font-weight: bold;
        }
        a {
            color: #3498db;
            text-decoration: none;
        }
        a:hover {
            text-decoration: underline;
        }
        .day-section {
            background-color: #fff;
            padding: 30px;
            margin-bottom: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }
        .day-intro-grid {
            display: grid;
            grid-template-columns: minmax(0, 1fr) minmax(0, 2fr);
            gap: 28px;
            align-items: start;
            margin: 18px 0 34px;
        }
        .day-intro-summary,
        .day-intro-map {
            min-width: 0;
        }
        .day-intro-summary h2,
        .day-intro-summary h3,
        .day-intro-summary h4,
        .day-intro-map h4 {
            margin-top: 0;
        }
        .day-intro-map a {
            display: block;
        }
        .day-intro-map img {
            display: block;
            width: 100%;
            max-width: none;
        }
        .day-hero-grid {
            display: grid;
            grid-template-columns: 1fr 1.2fr;
            gap: 20px;
            align-items: stretch;
            margin: 18px 0 24px;
            min-height: 350px;
        }
        .day-hero-summary {
            min-width: 0;
        }
        .day-hero-summary h2 {
            margin-top: 0;
        }
        .day-hero-map {
            min-width: 0;
            min-height: 350px;
        }
        .day-hero-map h4 {
            margin-top: 0;
            margin-bottom: 8px;
        }
        .day-hero-map iframe {
            width: 100%;
            height: calc(100% - 30px);
            min-height: 320px;
            border: none;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }
        .day-hero-poster {
            margin: 24px 0;
        }
        .day-hero-poster img {
            width: 100%;
            border-radius: 8px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }        .back-to-top {
            display: inline-block;
            margin-top: 20px;
            font-weight: bold;
            color: #e67e22;
        }
        hr {
            border: 0;
            height: 1px;
            background-color: #eee;
            margin: 40px 0;
        }
        pre {
            background-color: #f4f4f4;
            padding: 15px;
            border-radius: 5px;
            overflow-x: auto;
        }
        code {
            font-family: Consolas, Monaco, 'Andale Mono', 'Ubuntu Mono', monospace;
        }
        img {
            max-width: 100%;
            height: auto;
        }
        blockquote {
            border-left: 4px solid #3498db;
            padding-left: 15px;
            color: #666;
            margin-left: 0;
        }
        @media (max-width: 760px) {
            body {
                padding: 12px;
            }
            .day-section {
                padding: 18px;
            }
            .day-intro-grid {
                grid-template-columns: 1fr;
                gap: 18px;
            }
            .day-hero-grid {
                grid-template-columns: 1fr;
                min-height: auto;
            }
            .day-hero-map {
                min-height: 300px;
            }
        }
    </style>
</head>
<body>
    <div class="overview">
        ${mainHtml}
    </div>
    
    <hr>
    
    <div class="days-container">
        <h2>詳細每日行程</h2>
        ${daysHtml}
    </div>
    
    <script type="module">
        import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';
        mermaid.initialize({
            startOnLoad: true,
            securityLevel: 'loose',
            flowchart: { htmlLabels: true }
        });
    </script>
</body>
</html>
`;

fs.writeFileSync(outputHtmlPath, finalHtml);
console.log('Successfully generated index.html with all days embedded!');
