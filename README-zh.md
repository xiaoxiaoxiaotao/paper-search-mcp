# paper-search-mcp

一个面向 agent 的 MCP 服务，用来检索、读取和整理论文材料，方便后续做文献综述、对比分析和论文精读。

当前实现提供了两类核心能力：

- Semantic Scholar 检索与论文元数据读取
- arXiv 检索、单篇元数据读取、PDF 正文抽取

另外提供了一个跨源聚合工具，用来快速生成适合 agent 后续分析的 literature digest。

## 提供的 MCP Tools

### `search_semantic_scholar`

按查询词检索 Semantic Scholar，返回标准化后的论文列表，并按引用数降序排序。

参数：

- `query`: 检索词
- `max_results`: 返回上限，默认 `10`

### `get_semantic_scholar_paper`

按 `paper_id` 获取单篇论文详细元数据。

### `search_arxiv`

按查询词检索 arXiv。

参数：

- `query`: 检索词
- `max_results`: 返回上限，默认 `10`
- `sort_by`: `relevance`、`lastUpdatedDate`、`submittedDate`
- `sort_order`: `ascending` 或 `descending`

### `get_arxiv_paper`

按 arXiv ID、摘要页 URL 或 PDF URL 获取单篇论文元数据。

### `read_arxiv_paper`

下载 arXiv PDF，抽取前几页正文文本并返回结构化阅读材料。

参数：

- `arxiv_id_or_url`: arXiv ID、摘要页 URL 或 PDF URL
- `max_pages`: 抽取页数上限，默认 `8`
- `max_characters`: 返回文本字符上限，默认 `20000`

### `build_literature_digest`

跨 Semantic Scholar 和 arXiv 聚合检索、去重并返回一个简化版文献综述素材包。

适合让 agent 后续执行：

- 找经典工作与近期工作
- 归纳方法路线
- 对比数据集、指标和限制

## 安装

推荐使用 `uv` 管理虚拟环境和依赖。

```bash
uv sync
```

这会在当前目录下创建 `.venv` 并安装项目依赖。

如果你希望带开发依赖一起装：

```bash
uv sync --group dev
```

如果你有 Semantic Scholar API Key，可以配置：

```bash
export S2_API_KEY=your_key_here
```

可选环境变量：

- `S2_API_KEY`: Semantic Scholar API key
- `PAPER_MCP_HTTP_TIMEOUT`: HTTP 超时时间，默认 `30`
- `PAPER_MCP_USER_AGENT`: 自定义 User-Agent
- `PAPER_MCP_CACHE_DIR`: 自定义 PDF 下载缓存目录

### 作为 Python 包安装

如果你希望直接按 Python 包方式部署，可以：

```bash
pip install .
```

从仓库安装：

```bash
pip install https://github.com/xiaoxiaoxiaotao/paper-search-mcp.git
```


## 运行

### 直接启动

```bash
uv run paper-search-mcp
```

### MCP Client 配置示例

```json
{
	"servers": {
		"paper-search": {
			"type": "stdio",
			"command": "uv",
			"args": [
				"run",
				"--no-sync",
				"paper-search-mcp"
			],
			"cwd": "/home/tao/code/projects/paper-search-mcp",
			"env": {
				"S2_API_KEY": "${input:s2-api-key}"
			}
		}
	},
	"inputs": [
		{
			"type": "promptString",
			"id": "s2-api-key",
			"description": "Semantic Scholar API key",
			"password": true
		}
	]
}
```

如果你不想使用输入框，也可以改用 `envFile`，并在对应文件里写入 `S2_API_KEY=your_key_here`。



## 设计说明

- Semantic Scholar 适合找高引用、较成熟的相关工作
- arXiv 适合抓近期论文和读取 PDF 正文
- `build_literature_digest` 负责把两边结果合在一起，降低 agent 自己拼接上下文的成本
- `read_arxiv_paper` 不直接做主观结论，而是返回文本和分析提示，避免把分析逻辑硬编码进工具里
- npm 包可以做，但本质上只会是 Python 或 Docker 的包装层，不是这个项目最自然的主发布形式

## 后续可扩展方向

- 增加引用网络和相似论文检索