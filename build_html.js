const fs = require('fs');
const path = require('path');
const { marked } = require('marked');

// Custom renderer to handle some specific markdown formatting or we can just replace string after.
const indexMdPath = path.join(__dirname, 'index.md');
const outputHtmlPath = path.join(__dirname, 'index.html');


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

blueWords.forEach(word => {
    // We only replace exact matches that are not already inside HTML tags if possible.
    // Given the simple markdown, just global replace should work if we are careful.
    const regex = new RegExp(word, 'g');
    indexContent = indexContent.replace(regex, `<span class="blue-text">${word}</span>`);
});

let mainHtml = marked.parse(indexContent);

let daysHtml = '';
for (let i = 1; i <= 10; i++) {
    const dayMdPath = path.join(__dirname, `day${i}`, `day${i}.md`);
    if (fs.existsSync(dayMdPath)) {
        let dayContent = fs.readFileSync(dayMdPath, 'utf-8');
        // also color blue words in day content just in case
        blueWords.forEach(word => {
            const regex = new RegExp(word, 'g');
            dayContent = dayContent.replace(regex, `<span class="blue-text">${word}</span>`);
        });
        
        let dayHtmlParsed = marked.parse(dayContent);
        
        // Fix image paths (relative to the day directory, now from root)
        dayHtmlParsed = dayHtmlParsed.replace(/src="\.\//g, `src="./day${i}/`);
        dayHtmlParsed = dayHtmlParsed.replace(/href="\.\//g, `href="./day${i}/`);

        // Convert mermaid code blocks to div.mermaid
        dayHtmlParsed = dayHtmlParsed.replace(/<pre><code class="language-mermaid">([\s\S]*?)<\/code><\/pre>/g, '<div class="mermaid">\n$1\n</div>');

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
        .back-to-top {
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
        import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.esm.min.mjs';
        mermaid.initialize({ startOnLoad: true });
    </script>
</body>
</html>
`;

fs.writeFileSync(outputHtmlPath, finalHtml);
console.log('Successfully generated index.html with all days embedded!');
