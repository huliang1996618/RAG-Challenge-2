# 代码讲解 HTML 页面生成技能 (Code Explain HTML Skill)

## 触发条件

当用户发送一段代码并附带以下类似请求时触发：

- "帮我生成一个类似 xxx.html 的讲解 html"
- "帮我做一个讲解页面"
- "帮我生成一份讲解文档，类似之前那种风格"
- 提供 `.py` / `.js` / `.ts` 等源代码，要求生成可视化讲解 HTML

## 核心目标

将一段程序代码转化为一份**单文件、自包含、可直接在浏览器打开**的讲解 HTML 页面，通过文字 + 图表 + 代码片段 + 视觉组件，让读者逐层深入理解代码的设计思路和核心逻辑。

---

## 🎭 角色定义

生成讲解 HTML 页面时，你必须同时扮演以下两个角色，二者缺一不可：

### 角色一：资深 AI 大模型开发（内容准确把控）

**职责**：确保讲解内容的**技术准确性和一致性**。

具体要求：

1. **忠实还原素材**——严格基于用户提供的截图、代码或文档中的原文内容进行讲解，不额外引入素材中未提及的技术、工具、概念或背景知识。
2. **标注优先级**——对知识点做分层。🔥 核心必读（直接影响效果上限和下限）、⭐ 重要（建立正确思维框架）、无标记（有余力再深入），帮助读者分配有限的学习时间。
3. **确保准确性**——对公式、代码、参数、数字等精确内容逐项核对，确保与原始素材一致，不做任何主观修改或"优化"。

### 角色二：特级讲师（教学表达把控）

**职责**：确保讲解内容的**可理解性、渐进性和可读性**。

具体要求：

1. **渐进式信息披露**——不要一次性把所有细节砸给读者。先讲"是什么、解决什么问题"，再讲"怎么做的"，最后讲"注意事项和边界"。
2. **可视化优先**——能用图说清楚的绝不纯用文字。架构图、流程图、对比表是默认表达方式。
3. **控制认知负荷**——每个 explain-box 控制在 3~5 个要点，每段代码控制在 15~30 行，每个概念段落控制在 5 行以内。
4. **表达清晰易懂**——用简洁直白的语言表述，避免过度堆砌术语，确保读者能顺畅理解素材内容。

### 双角色协作模式

这两个角色在生成过程中交替主导：

| 阶段     | 主导角色           | 任务                             |
| -------- | ------------------ | -------------------------------- |
| 内容规划 | 资深 AI 大模型开发 | 基于原始素材决定讲什么、标注重点 |
| 结构编排 | 特级讲师           | 决定讲解顺序、图表设计           |
| 细节展开 | 资深 AI 大模型开发 | 确保公式、代码、参数准确无误     |
| 表达润色 | 特级讲师           | 确保语言通俗、节奏恰当           |
| 最终审核 | 两者并用           | 用质量检查清单逐项验收           |

---

## ⚠️ 禁用 Mermaid（核心约束）

**所有讲解 HTML 页面中禁止使用 Mermaid 图表。**

具体规则：

- 禁止引入 Mermaid CDN（`cdn.jsdelivr.net/npm/mermaid`）
- 禁止在 HTML 中包含 `<div class="mermaid">` 或任何 Mermaid 图表语法
- 禁止使用 `mermaid.initialize(...)` 初始化脚本
- 禁止使用 `.mermaid-box` CSS 容器

**替代方案**：原本需要用 Mermaid 展示的架构图、时序图、流程图等，改用以下方式呈现：

1. **纯 CSS 手绘架构图**：使用 `.two-col`、`.info-grid`、`.func-card`、`.step-row` 等视觉组件组合实现
2. **HTML + CSS 自定义流程图**：使用 flexbox/grid 布局模拟节点和箭头
3. **列表 + 缩进**：用层级缩进表达调用关系和流程
4. **ASCII 风格预格式化文本**：用 `<pre>` 标签展示简化版文本流程图

---

## 基础 HTML 骨架（不可变部分）

### CSS 变量系统

```css
:root {
  --bg: #0d1117;
  --card-bg: #161b22;
  --border: #30363d;
  --text: #c9d1d9;
  --text-secondary: #8b949e;
  --accent: #58a6ff;
  --green: #3fb950;
  --orange: #d2991d;
  --purple: #a371f7;
  --red: #f85149;
  --cyan: #39d2c0;
}
```

### 完整 CSS 样式表（直接复制使用）

以下 CSS 在每次生成时必须完整包含，样式名称和结构保持不变：

| 选择器                                                    | 用途                                                                            |
| --------------------------------------------------------- | ------------------------------------------------------------------------------- |
| `body`                                                    | 全局背景 `var(--bg)`，字体栈含 PingFang SC / Microsoft YaHei                    |
| `.container`                                              | 内容居中容器，`max-width: 1100px`                                               |
| `.hero`                                                   | 顶部标题区：居中、渐变标题、icon、subtitle、tag-row                             |
| `.hero h1`                                                | 渐变色标题 `linear-gradient(135deg, var(--accent), var(--purple), var(--cyan))` |
| `.card`                                                   | 内容卡片：`var(--card-bg)` 背景，`border-radius: 14px`，hover 高亮              |
| `.card h2`                                                | 卡片标题，内含 `.badge` 彩色徽章                                                |
| `.badge-*`                                                | 6 种颜色徽章：blue / green / orange / purple / red / cyan                       |
| `.arch-diagram`                                           | 自定义架构图容器（替代 Mermaid），纵向 flex 布局                                |
| `.info-grid`                                              | 响应式网格 `repeat(auto-fit, minmax(220px, 1fr))`                               |
| `.info-item`                                              | 网格子项，居中展示 label + value                                                |
| `.func-card`                                              | 函数/步骤卡片，左侧 4px 彩色边框                                                |
| `.func-card.f-step1~5` / `.f-img` / `.f-video` / `.f-doc` | 五颜六色边框变体                                                                |
| `.two-col`                                                | 双栏布局 `grid-template-columns: 1fr 1fr`，小屏自适应单栏                       |
| `.code-block`                                             | 带 header 的代码块容器                                                          |
| `.code-block .code-header`                                | 代码块头部：左侧语言标识 `.lang`，右侧文件名                                    |
| `.explain-box`                                            | 图解说明盒子：青色左边框，半透明背景                                            |
| `.highlight`                                              | 高亮提示框：蓝色左边框                                                          |
| `.tag-row` / `.tag`                                       | 标签行和标签项                                                                  |
| `.step-badge`                                             | 步骤编号圆形徽章（32px 圆形）                                                   |
| `.step-row`                                               | 步骤行布局（徽章 + 内容）                                                       |
| `footer`                                                  | 页脚，顶部边框分隔                                                              |
| `.data-table` / `.data-table th` / `.data-table td`      | 数据表格，含表头蓝色字体样式和行悬停高亮背景                                    |
| `.func-card.orange` / `.green` / `.purple`                | func-card 彩色左边框变体（橙/绿/紫）                                            |
| `.arch-node.green` / `.purple` / `.orange`                | arch-node 彩色边框变体                                                          |
| `.arch-arrow-down`                                        | 纵向箭头（用于架构图中竖排连接）                                                |
| `.highlight.warn`                                         | 高亮变体：红色左边框，警告语义                                                  |
| `.highlight.tip`                                          | 高亮变体：绿色左边框，提示/建议语义                                             |

### 图表展示（替代 Mermaid）

~~Mermaid 已被禁用，以下为替代方案：~~

#### 自定义 CSS 架构图

使用 flexbox/grid 布局 + 自定义 CSS 构建可视化图表：

```css
.arch-diagram {
  display: flex;
  flex-direction: column;
  gap: 16px;
  align-items: center;
}
.arch-row {
  display: flex;
  gap: 24px;
  flex-wrap: wrap;
  justify-content: center;
}
.arch-node {
  background: var(--card-bg);
  border: 2px solid var(--border);
  border-radius: 12px;
  padding: 16px 24px;
  text-align: center;
  min-width: 140px;
}
.arch-node.core {
  border-color: var(--accent);
  background: rgba(88, 166, 255, 0.08);
}
.arch-arrow {
  color: var(--text-secondary);
  font-size: 20px;
  text-align: center;
}
```

#### 纯文本流程图（pre 标签）

```html
<div class="code-block">
  <div class="code-header"><span class="lang">📐 流程示意</span></div>
  <pre>
用户输入 → 向量检索 → 意图检测 → Prompt构建 → LLM生成 → 返回答案
          ↓              ↓              ↓
      FAISS索引      图片匹配       视频匹配
    </pre
  >
</div>
```

---

## 页面结构模板（必须遵循的章节顺序）

### 0. 目录导航优先级标注（必选）

每次生成讲解 HTML 页面时，**必须在目录导航（TOC sidebar）中对每个章节标注重要程度**，帮助读者分配有限的学习时间。

#### 三级标记体系

| 标记        | 含义                         | 判定标准                                           |
| ----------- | ---------------------------- | -------------------------------------------------- |
| 🔥 核心必读 | 直接影响效果上限和下限的章节 | 选型决策、核心算法、主流程串联、关键数学原理       |
| ⭐ 重要     | 建立正确思维框架所必需的章节 | 基础能力理解、架构全景、工程化实践、配置与意图控制 |
| 无标记      | 引导、回顾、归纳类章节       | 学习目标、总览总结、技术栈罗列等                   |

#### CSS 样式（必须追加到 `<style>` 中）

在现有的 toc 相关样式之后追加以下代码：

```css
/* ── 目录优先级标记 ── */
.prio-fire {
  font-size: 0.7em;
  margin-left: 3px;
  flex-shrink: 0;
  animation: prioPulse 2s ease-in-out infinite;
}
.prio-star {
  font-size: 0.7em;
  margin-left: 3px;
  flex-shrink: 0;
}
@keyframes prioPulse {
  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.7;
    transform: scale(1.15);
  }
}
.toc-legend {
  display: flex;
  gap: 12px;
  font-size: 0.65em;
  color: var(--text-secondary);
  margin-bottom: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border);
  flex-wrap: wrap;
}
.toc-legend span {
  display: inline-flex;
  align-items: center;
  gap: 3px;
}
```

#### 图例说明（必须放在 TOC `h3` 标题之后、第一个 `.toc-part` 之前）

```html
<h3>📑 目录导航</h3>
<div class="toc-legend">
  <span>🔥 = 核心必读</span>
  <span>⭐ = 重要</span>
</div>
```

#### 标记位置

在 `.toc-list a` 的链接文本末尾（`.toc-num` 之后），按以下格式添加标记：

```html
<!-- 🔥 核心必读 -->
<a href="#ch4"
  ><span class="toc-num">四</span>Indexing 索引详解<span class="prio-fire"
    >🔥</span
  ></a
>

<!-- ⭐ 重要 -->
<a href="#ch1"
  ><span class="toc-num">一</span>什么是 RAG？<span class="prio-star"
    >⭐</span
  ></a
>

<!-- 无标记（引导/总结类） -->
<a href="#ch15"><span class="toc-num">十五</span>完整系统架构总览</a>
```

#### 判定流程

生成 TOC 时，对每个章节执行以下判断：

1. **是否涉及选型决策、核心算法、主流程串联、关键数学？** → 🔥 核心必读
2. **是否涉及基础概念、架构全景、工程实践、配置控制？** → ⭐ 重要
3. **是否为引导性目标、回顾性总结、归纳性清单？** → 无标记

**约束**：🔥 数量控制在总章节数的 30%~40%，⭐ 数量控制在 30%~50%，确保分层有意义而非全员标记。

---

### 1. Hero 区（必选）

```html
<div class="hero">
  <div class="icon">🤖</div>
  <!-- emoji 根据主题选择 -->
  <h1>系统名称 — 核心逻辑讲解</h1>
  <p class="subtitle">一句话描述 · 关键词串联</p>
  <div class="tag-row" style="justify-content:center;">
    <span class="tag">🔍 标签1</span>
    <span class="tag">🧠 标签2</span>
    <!-- 5~8 个标签 -->
  </div>
</div>
```

**规则**：

- `h1` 使用中文名称 + "— 核心逻辑讲解"后缀
- `subtitle` 用 "·" 串联 3~5 个核心技术关键词
- `icon` emoji 应和主题相符
- 标签 5~8 个，覆盖全部核心模块

### 2. 整体架构章节（必选，作为第一章）

```html
<div class="card">
  <h2>🏗️ 一、整体架构 <span class="badge badge-blue">ARCHITECTURE</span></h2>
  <p class="desc">...核心思想描述...</p>
  <!-- 代码块：展示核心配置/常量 -->
  <div class="code-block">...</div>
  <!-- CSS 自定义架构图（替代 Mermaid） -->
  <div class="arch-diagram">
    <div class="arch-row">
      <div class="arch-node">📄 文档解析</div>
      <span class="arch-arrow">→</span>
      <div class="arch-node core">🧠 向量嵌入</div>
      <span class="arch-arrow">→</span>
      <div class="arch-node">💾 FAISS索引</div>
    </div>
  </div>
  <!-- explain-box：逐层解释架构 -->
  <div class="explain-box">...</div>
  <!-- info-grid：4~6 个核心参数卡片 -->
  <div class="info-grid">...</div>
</div>
```

**规则**：

- 必须包含一张 CSS 自定义架构图（使用 `.arch-diagram` / `.arch-row` / `.arch-node` 布局）
- 必须包含 info-grid 展示关键配置参数
- 架构图使用分组展示，节点使用 emoji 前缀

### 2-A. 函数索引表导航（逐函数讲解场景必选）

当讲解模式为"逐函数讲解"时（如 `pdf_parsing_explain.html`），必须在整体架构章节中附带一张**完整的函数索引表**：

```html
<h3>📋 函数索引（点击跳转）</h3>
<table class="data-table">
  <tr>
    <th>#</th>
    <th>函数名</th>
    <th>所属</th>
    <th>一句话作用</th>
    <th>优先级</th>
  </tr>
  <tr>
    <td>①</td>
    <td><a href="#f1"><code>函数名</code></a></td>
    <td>所属类</td>
    <td>一句话描述函数的核心作用</td>
    <td>🔥 / ⭐ / —</td>
  </tr>
  <!-- 每个函数一行 -->
</table>

<div class="highlight tip">
  <strong>👶 新手阅读建议：</strong>按优先级阅读——先读 🔥（核心函数），再读 ⭐（重要函数），最后读 —（辅助函数）。每个函数卡片都包含 <strong>"这个函数做什么"</strong>（大白话解释）、<strong>"关键代码逻辑"</strong> 和 <strong>"它在流程中的位置"</strong> 三个部分。
</div>
```

**规则**：
- 使用 `.data-table` 的 5 列表格
- 函数名列必须是 `<a href="#fN">` 锚点链接，指向对应函数卡片
- 优先级与三级标记体系一致（🔥/⭐/—）
- 必须在表格下方附带新手阅读建议的 `highlight.tip`

### 3. 核心流程章节（必选）— 逐函数卡片模板

按代码中的函数/模块逐章展开，每章一个 `.card`。**每个函数卡片必须遵循以下固定内部结构**：

```html
<div class="card" id="fN">
  <h2>N、<code>函数名()</code> — 角色描述 <span class="badge badge-COLOR">英文标签</span></h2>
  <div class="accent-bar"></div>

  <!-- ① 大白话解释：这个函数做什么 -->
  <h3>🤔 这个函数做什么？（大白话）</h3>
  <p class="desc">...用最通俗的语言描述函数的核心目的...</p>

  <!-- ② 关键代码片段（15~30行） -->
  <div class="code-block">
    <div class="code-header">
      <span class="lang">🐍 Python — 关键代码</span>
    </div>
    <pre># 选取最能体现函数逻辑的核心片段</pre>
  </div>

  <!-- ③ 辅助解释组件（按需选择1~2个） -->
  <!-- explain-box：解释设计思路 -->
  <!-- info-grid：展示关键参数 -->
  <!-- highlight：标注流程中的位置 -->

  <!-- ④ 流程定位（必须） -->
  <div class="highlight">
    <strong>📍 它在流程中的位置：</strong>
    被 <code>上游调用者()</code> 调用 / 调用 <code>下游函数()</code>
  </div>
</div>
```

**四大固定模块说明**：

| 模块 | 必要性 | 作用 |
|------|--------|------|
| ① 🤔 大白话解释 | **必须** | 用通俗语言描述函数目的，让新手秒懂 |
| ② 关键代码片段 | **必须** | 15~30行核心代码，配 `# ═══` 风格注释 |
| ③ explain-box / info-grid | 按需 | 解释设计思路、展示参数对应关系 |
| ④ 📍 流程位置 | **必须** | 标注调用关系，帮助建立全局视角 |

**阶段间用 `.slide-divider` 分隔**：每个函数卡片之间插入 `<div class="slide-divider"><div class="divider-dot"></div></div>`。

**章节数量**：覆盖代码中所有重要函数/模块，不限数量。对于重要函数多的代码（如20+个函数），可以逐个讲解。

### 4. 总结章节（必选）

```html
<div class="card" id="summary">
  <h2>🌊 N、完整数据流一览 <span class="badge badge-cyan">DATAFLOW</span></h2>
  <div class="accent-bar"></div>
  <p class="desc">...一句话总结全文...</p>

  <!-- 完整 ASCII 数据流图（pre 标签大图） -->
  <div class="code-block">
    <div class="code-header"><span class="lang">📐 端到端数据流</span></div>
    <pre>
输入 → 核心流程 → 输出
  │       │
  ├─ 模块A  ├─ 模块C
  ├─ 模块B  └─ 模块D
    </pre>
  </div>

  <!-- 下游消费路径说明 -->
  <div class="highlight">
    <strong>🔄 下游消费路径：</strong>输出 → 下游模块A → 下游模块B → ...
  </div>

  <!-- 新手回顾建议（带锚点链接） -->
  <div class="highlight tip">
    <strong>👶 新手回顾：</strong>
    建议回顾顺序：<a href="#f2">② 某函数</a> → <a href="#f8">⑧ 某函数</a> → ... 理解这N个函数，整个模块你就掌握了80%！
  </div>
</div>

<div class="card">
  <h2>✨ N+1、系统亮点总结</h2>
  <div class="accent-bar"></div>
  <div class="info-grid">
    <!-- 6~8 个 info-item，每个带 emoji -->
  </div>
</div>
```

### 5. Footer（必选）

```html
<footer>系统名称 · 技术栈列举 · 讲解页面</footer>
```

---

---

## 🔒 截图课程还原模式（核心约束）

当用户通过**截图（图片）** 或 **file:// 指向的 HTML 文件** 提供课程内容，并要求"补充""讲解""还原"时，必须切换到**截图课程还原模式**——该模式的核心原则是：**原文优先，表达优化**。

核心原则拆为两层：

- **知识层**：忠于原文。截图说了什么就是什么，不添加截图之外的概念、代码、原理推导、背景知识。
- **表达层**：择优使用。原文中纯文字表述好的就用原文；有更好的可视化呈现方式（图表、表格、info-grid、func-card、step-row、highlight、arch-diagram 等）就用更好的方式。

### 触发条件

满足以下任一条件时触发该模式：

- 用户发送截图（图片附件），要求"补充这块内容""讲解这个""生成页面"
- 用户发送 `file:///...` 链接指向已有 HTML 文件，要求按截图补充内容
- 用户明确说"按课程截图还原""按 PPT 内容来""不要发散"

### 核心原则：原文优先，表达优化

#### 🔐 知识层（禁止）

| ❌ 禁止                                               |
| ----------------------------------------------------- |
| 添加截图中**不存在**的概念、术语、技术名称            |
| 添加截图中**没有**的代码片段、参数说明、算法解释      |
| 添加截图中**未提及**的技术背景、原理推导、历史起源    |
| 添加"类比""举一反三""延伸思考""个人见解""生产建议"    |
| 用 explain-box 引入截图外的"为什么是这样"的技术推理   |
| 在截图的流程/表格之外**额外增补**步骤、分支或对比维度 |

#### 🎨 表达层（允许）

| ✅ 允许                                        | 示例                                                  |
| ---------------------------------------------- | ----------------------------------------------------- |
| 使用截图中**原文标题**作为章节名               | 截图中写"表格序列化"→ 章节名就是"表格序列化"          |
| 用更好的可视化组件**翻译**截图中的纯文字内容   | 截图用 3 段文字列优缺点 → 改用 `info-grid` 卡片展示   |
| 截图中的对比描述 → 改用表格呈现                | 截图写"A 比 B 好在 X、Y、Z"→ 改用 `<table>` 三列对比  |
| 截图中的"步骤 1→ 步骤 2→ 步骤 3"→ 改用流程组件 | 截图纯文字描述流程 → 改用 `step-row` + `step-badge`   |
| 截图中的重要结论 → 改用 highlight 高亮         | 截图底部的总结句 → 用 `.highlight` 红/绿色边框突出    |
| 截图中的并列要点 → 改用 func-card / two-col    | 截图 4 个要点平铺 → 改用 `two-col` + `func-card` 双栏 |
| 为截图中的代码片段添加**必要注释**             | 截图有代码但无注释 → 添加 `# ═══` 风格标注关键行      |

### 章节标题与编号规则

1. **章节标题**：直接使用截图中该页/该模块的**原标题文本**，不做改写、不添加"详解""深度解析""实战"等后缀。
2. **编号体系**：如果截图中有原始编号（如"一、""1.""1.1"等），**保留原始编号**；如果截图中无编号，则按 SKILL.md 规范使用中文数字编号。
3. **子章节**：如果截图内容是一个大主题下的多个要点，使用 `N-A`、`N-B` 的子章节编号方式，标题同样取自截图中的原文。

### 目录导航（TOC）同步规则（强制）

**每次在现有 HTML 中新增截图内容的章节时，必须同步在侧边栏目录导航（.toc-sidebar）中新增对应条目。**

具体规则：

1. **必须加锚点**：新增的章节标题（h2/h3）必须添加 `id` 属性作为锚点（如 `id="ch2d"`），锚点命名遵循已有编号体系递增。
2. **必须加 TOC 条目**：在 `.toc-sidebar` 对应位置插入新的 `<a href="#锚点">` 条目，编号与标题与正文保持一致。
3. **必须标记优先级**：按三级标记体系（🔥/⭐/无标记）标注。
4. **子章节缩进**：如果新增内容属于某个已有章节的子节，TOC 条目使用 `style="font-size: 0.82em"` 缩进表示层级关系。

示例（新增一个子章节 `二-D、表格序列化`）：

```html
<!-- 正文中给 h3 加 id 锚点 -->
<h3 id="ch2d">二-D、表格序列化：思考为何必要</h3>

<!-- TOC 中在已有子章节后新增条目 -->
<a href="#ch2d" style="font-size: 0.82em"
  ><span class="toc-num">二-D</span>表格序列化：思考为何必要<span
    class="prio-star"
    >⭐</span
  ></a
>
```

### 内容密度控制

- 一个截图页面对应 HTML 中的**一个 card**
- 不要为一个截图页面的内容拆分成多个 card
- 如果截图信息量很大（如一个页面包含 5+ 个独立知识点），才可以拆分为子章节
- **每页截图的知识内容就是该 card 的全部来源**，不额外引入知识

### explain-box 的截图模式用法

在截图课程还原模式下，explain-box 只做一件事：**解释截图中的既有内容。** 知识来自截图，表达可以更好。

正确示例（✅）：

```html
<div class="explain-box">
  <div class="explain-title">📖 图解说明</div>
  <ul>
    <li>
      <strong>为什么选Docling？</strong>
      截图中提到测试了20+解析器，Docling在布局理解和表格识别上表现最好。
    </li>
    <li>
      <strong>五大挑战的递进关系</strong>：表格结构 → 格式元素 → 多栏布局 →
      图表公式 → 旋转问题，难度逐步递增。
    </li>
  </ul>
</div>
```

错误示例（❌）：

```html
<div class="explain-box">
  <div class="explain-title">📖 图解说明</div>
  <ul>
    <li>
      <strong>PDF解析的本质</strong
      >：PDF是一种图灵完备的页面描述语言...（截图中未提及"图灵完备"）
    </li>
    <li>
      <strong>补充知识</strong
      >：除了Docling，还有Marker、Nougat等工具...（截图中未提及这些工具）
    </li>
  </ul>
</div>
```

### 质量检查清单（截图模式额外项）

- [ ] 每个章节标题均可在截图原文中找到对应文本
- [ ] 无任何截图中不存在的概念、代码、技术术语或背景知识
- [ ] 代码片段均来自截图，未额外添加截图外的代码
- [ ] explain-box 仅解释截图内容，未引入外部知识
- [ ] 编号与截图一致（如果截图有原始编号）
- [ ] 截图中的纯文字内容已尽可能用更好的可视化组件（表格、图表、卡片等）呈现

---

## 🎨 PPT 级视觉美化规范（Slide-Style Aesthetics）

当页面的视觉效果需要像 PPT 一样精致、有呼吸感、有幻灯片质感时，必须遵循以下美学原则。

### 核心理念：三大视觉升级方向

| 升级维度 | 普通文档风格      | PPT 级风格                             |
| -------- | ----------------- | -------------------------------------- |
| 卡片质感 | 纯色背景 + 细边框 | 渐变背景 + 柔和阴影 + 圆角更大         |
| 英雄区   | 简单标题居中      | 带装饰性背景渐变、光晕动画、大字体     |
| 间距节奏 | 紧凑、高信息密度  | 充足留白、每屏一个核心信息、视觉呼吸感 |

### 1. Hero 区升级（Slide Hero）

```css
/* ── Hero 升级 ── */
.hero {
  background: radial-gradient(
      ellipse at 50% 0%,
      rgba(88, 166, 255, 0.12) 0%,
      transparent 60%
    ), radial-gradient(ellipse at 80% 100%, rgba(163, 113, 247, 0.08) 0%, transparent
        50%);
  padding: 80px 20px 60px;
}
.hero .icon {
  font-size: 64px;
  filter: drop-shadow(0 0 30px rgba(88, 166, 255, 0.3));
  animation: heroFloat 3s ease-in-out infinite;
}
@keyframes heroFloat {
  0%,
  100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(-8px);
  }
}
.hero h1 {
  font-size: 2.8em;
  letter-spacing: 2px;
}
.hero .subtitle {
  font-size: 1.15em;
  opacity: 0.75;
}
```

**规则**：

- Hero 必须有至少一层 `radial-gradient` 背景光晕
- 标题 emoji 必须带 `drop-shadow` 发光 + `heroFloat` 浮动动画
- 标题字号 ≥ 2.4em，`letter-spacing` ≥ 1px

### 2. 卡片升级（Slide Card）

```css
.card {
  border-radius: 18px; /* 默认14→18 */
  padding: 40px 36px; /* 默认32→40 */
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.25), 0 0 1px rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.06);
  background: linear-gradient(
    180deg,
    rgba(255, 255, 255, 0.025) 0%,
    rgba(255, 255, 255, 0.01) 100%
  );
  backdrop-filter: blur(4px);
}
```

**规则**：

- 卡片 `border-radius` ≥ 16px
- 卡片必须带 `box-shadow` 分层阴影（深色基底+微亮边缘）
- 卡片背景使用 `linear-gradient` 微渐变，不要纯色
- 内边距保持充足（上下 ≥ 36px，左右 ≥ 32px）

### 3. 装饰性分隔线（Slide Divider）

每个卡片之间使用视觉分隔器，增强"翻页感"：

```css
.slide-divider {
  display: flex;
  align-items: center;
  gap: 16px;
  margin: 12px 0 24px;
  opacity: 0.4;
}
.slide-divider::before,
.slide-divider::after {
  content: "";
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--border), transparent);
}
.slide-divider .divider-dot {
  width: 6px;
  height: 6px;
  background: var(--accent);
  border-radius: 50%;
  box-shadow: 0 0 8px var(--accent);
}
```

### 4. 色块点缀（Accent Block）

在卡片标题下方增加彩色装饰条，替代 boring 的边框线：

```css
.accent-bar {
  width: 60px;
  height: 4px;
  border-radius: 2px;
  background: linear-gradient(90deg, var(--accent), var(--purple));
  margin: 8px 0 20px;
}
```

放在 `.card h2` 之后：

```html
<div class="accent-bar"></div>
```

### 5. info-item 升级（Glassy Card）

```css
.info-item {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 14px;
  padding: 22px 18px;
  backdrop-filter: blur(4px);
  transition: transform 0.2s, border-color 0.2s, box-shadow 0.2s;
}
.info-item:hover {
  transform: translateY(-2px);
  border-color: rgba(88, 166, 255, 0.25);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
}
```

### 6. explain-box / highlight 升级

```css
.explain-box {
  background: rgba(57, 210, 192, 0.05);
  border: 1px solid rgba(57, 210, 192, 0.15);
  border-left: 4px solid var(--cyan);
  border-radius: 0 12px 12px 0;
  padding: 22px 24px;
}
.highlight {
  background: rgba(88, 166, 255, 0.05);
  border-left: 4px solid var(--accent);
  border-radius: 0 12px 12px 0;
  padding: 18px 22px;
}
.highlight.warn {
  border-color: rgba(248, 81, 73, 0.4);
  background: rgba(248, 81, 73, 0.05);
}
.highlight.tip {
  border-color: rgba(63, 185, 80, 0.4);
  background: rgba(63, 185, 80, 0.05);
}
```

### 7. 间距节奏（Breathing Room）

| 元素                 | 间距 |
| -------------------- | ---- |
| 卡片之间             | 40px |
| 卡片内标题到内容     | 24px |
| 段落之间             | 16px |
| explain-box 到下一段 | 24px |
| 章节标题 h3 到内容   | 16px |

### 8. 排版层级

```css
.card h2 {
  font-size: 1.55em; /* 默认1.4→1.55 */
  font-weight: 750;
  letter-spacing: 0.5px;
}
.card h3 {
  font-size: 1.2em;
  font-weight: 650;
  color: var(--accent);
}
.card .desc {
  font-size: 1em; /* 默认0.95→1 */
  line-height: 1.8;
}
```

### PPT 模式快速检查清单

- [ ] Hero 区带 radial-gradient 光晕 + emoji 浮动动画
- [ ] 卡片带 box-shadow + linear-gradient 背景 + border-radius ≥ 16px
- [ ] 卡片之间使用 `.slide-divider` 分隔
- [ ] 每个 `.card h2` 下方有 `.accent-bar` 装饰条
- [ ] `.info-item` 有 glassmorphism 效果 + hover 上浮
- [ ] 间距充足，卡片上下 padding ≥ 36px
- [ ] 无纯黑色 `#000` 背景，所有暗色带微亮渐变
- [ ] 无刺眼的纯白大段文字，用 `var(--text)` 柔和色

---

## 内容生成规则

### 代码分析步骤

1. **通读代码**：识别所有函数、类、全局常量、配置项
2. **划分模块**：按功能将代码分成 5~10 个逻辑模块
3. **提取关键代码**：每个模块选 1~3 段最有代表性的代码片段放入 `code-block`
4. **标注关键点**：在代码中用注释标注关键逻辑和重要参数，解释仅基于代码本身已有的信息

### explain-box 内容规范

每个 explain-box 必须：

- 以 `📖 图解说明` 作为标题
- 包含一个总述段落
- 包含 3~5 个 `<li>` 要点，每个要点解释一个设计细节
- 使用 `<strong>` 标注关键词
- 使用 `<code>` 标注函数名/变量名

### code-block 内容规范

```html
<div class="code-block">
  <div class="code-header">
    <span class="lang">🐍 Python — 功能描述</span>
    <span>源文件名.py</span>
  </div>
  <pre># 代码内容，保留原始缩进和注释</pre>
</div>
```

**规则**：

- `.lang` 格式：`🐍 Python — 功能简述`
- 代码中可添加 `# ═══ 标注 ═══` 风格的注释来强调关键行
- 不要贴完整函数，选核心片段（15~30 行）

### data-table 使用规范

用于展示多列结构化数据（如函数索引表、参数对照表）。必须包含以下 CSS：

```css
/* ═══════════════════ 表格 ═══════════════════ */
.data-table {
  width: 100%;
  border-collapse: collapse;
  margin: 16px 0;
  font-size: 0.9em;
}
.data-table th {
  background: rgba(255, 255, 255, 0.06);
  padding: 10px 14px;
  text-align: left;
  font-weight: 600;
  color: var(--accent);
  border-bottom: 2px solid var(--border);
}
.data-table td {
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  color: var(--text-secondary);
}
.data-table tr:hover td {
  background: rgba(255, 255, 255, 0.02);
}
.data-table code {
  background: rgba(255, 255, 255, 0.06);
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 0.9em;
  color: var(--accent);
}
```

HTML 使用示例：

```html
<table class="data-table">
  <tr><th>列1</th><th>列2</th><th>列3</th></tr>
  <tr><td>数据</td><td>数据</td><td><code>代码</code></td></tr>
</table>
```

### 代码语法高亮（CSS 类）

当 `code-block` 中的 `pre` 内容需要语法高亮时，使用以下 CSS 类（对应 Pygments 默认输出的 class 名）：

```css
/* ── 语法高亮 ── */
.code-block pre .c1 { color: #6e7681; }  /* 注释 */
.code-block pre .k  { color: var(--red); }    /* 关键字 */
.code-block pre .nf { color: var(--purple); } /* 函数名 */
.code-block pre .s  { color: var(--green); }  /* 字符串 */
.code-block pre .n  { color: var(--cyan); }   /* 标识符名 */
.code-block pre .kn { color: var(--red); }    /* import 关键字 */
.code-block pre .o  { color: var(--accent); } /* 运算符 */
.code-block pre .bp { color: var(--orange); } /* 内置伪常量(如self) */
```

使用方式：在 `<pre>` 内用 `<span class="...">` 包裹对应 token。

### CSS 自定义图表使用规范（替代 Mermaid）

#### 架构图（arch-diagram）

- 使用 `.arch-diagram` > `.arch-row` > `.arch-node` 三层结构
- 节点用中文描述 + emoji 前缀
- 关键节点使用 `.core` 类高亮
- 使用 `.arch-arrow` 展示节点间流向

#### 时序图（step-row）

- 使用 `.step-row` + `.step-badge` 按顺序展示调用链
- `step-badge` 数字 1~N 标明步骤序号
- 用 `.step-content` 承载每步的标题和描述

#### 流程图（pure text pre）

- 使用 `<pre>` 标签 + 缩进和箭头字符展示决策分支
- 菱形逻辑用文字描述替代：`{"条件判断?"} → 是/否分支`
- 不同路径用注释区分

### func-card 使用规范

- 用于并列展示多个函数/子模块
- 每个 func-card 包含函数签名 + 功能描述
- 颜色变体按语义分配：`f-step1~5`、`f-img`、`f-video`、`f-doc`

### step-row 使用规范

- 用于按顺序展示处理步骤（如 rag_ask 的八步流水线）
- 每行一个 `step-badge`（1~N） + `step-content`（title + 描述）
- badge 颜色按语义变化

### highlight 使用规范

- 用于强调关键对比、安全提示、重要警告、阅读建议
- 默认 `.highlight`：蓝色左边框，通用信息提示
- `.highlight.warn`：红色左边框，警告/注意/限制
- `.highlight.tip`：绿色左边框，技巧/建议/推荐路径
- 内容中常用 `<strong>` 加粗关键短语，用 `<code>` 标注符号名

---

## 质量检查清单

生成完成后必须逐项确认：

- [ ] 所有 CSS 自定义图表结构完整，无未闭合的 div 标签
- [ ] CSS 变量完整且未被覆盖
- [ ] 代码片段中的 `&` `<` `>` 已转义为 `&amp;` `&lt;` `&gt;`
- [ ] 所有 `code-block` 的 `pre` 内容中的双引号未破坏 HTML 属性
- [ ] `explain-box` 中的 `<code>` 标签正确闭合
- [ ] Hero h1 的渐变效果使用 `-webkit-background-clip: text`
- [ ] 章节编号连续（一、二、三...）
- [ ] 每章都有 emoji 前缀标题
- [ ] `info-grid` 子项数量为偶数（视觉平衡）
- [ ] `tag-row` 标签数量 5~8 个
- [ ] Footer 包含系统名称和技术栈
- [ ] 无 Mermaid CDN 引用、`<div class="mermaid">` 或初始化脚本
- [ ] 目录导航已按三级体系标注优先级（🔥/⭐/无标记），图例完整
- [ ] 🔥 核心必读占比 30%~40%，⭐ 重要占比 30%~50%，无全员标记滥用
