# OnlyClaws ESP ADL 规则

与 [mcp_guard](https://github.com/shinjiyu/mcp_guard) 使用**同一套**门禁工具：`scripts/adl_check.py` + Structurizr DSL + `graph.json` / `requirements.json`。

## 1. 出度 O(1)

对业务插件集合 \(P\)（`graph.json` 中 `role: plugin`）：

\[
\forall p\in P:\ \mathrm{out}(p)\le K
\qquad (K=2\ \text{默认：contracts + 可选 infra})
\]

\[
\forall p_1,p_2\in P:\ (p_1,p_2)\notin E
\]

插件出边只允许指向 `contracts` 或 `infra`。

**不**约束：`contracts` / `compose` 的入度（允许 \(O(n)\)）。

## 2. 单测集与功能差集

\[
R_U=\{r\in R\mid r.\mathrm{test\_kind}\in\{\mathrm{unit},\mathrm{contract}\}\ \land\ r.\mathrm{tests}\neq\emptyset\}
\]

\[
R_{\mathrm{manual}}=R\setminus R_U
\]

| test_kind | 含义 | 收工方式 |
|-----------|------|----------|
| `unit` | 纯逻辑，单测蕴含功能 | Agent / CI |
| `contract` | 端口契约测 | Agent / CI |
| `manual` | 真机 / 云端联调 / 人工 | 人测清单 |
| `none` | 尚未分配 | **门禁失败** |

`adl_check.py` 打印 \(R_{\mathrm{manual}}\)；若存在 `test_kind: none` 或 unit/contract 但 `tests` 为空 → fail。  
`ui:true` 必须走 UX → 实现 → UI（与 mcp_guard 相同字段）。本仓当前以设备/云端为主，多数需求 `ui:false`。

## 3. 变更顺序

1. 改 `requirements.json` / `graph.json` / `workspace.dsl`
2. 跑 `python scripts/adl_check.py`
3. 再改固件 / 控制面代码与测试
4. 更新 `COMPONENT-TEST-MAP.md` / `modules-catalog.md`

## 4. 产品矩阵（编译期插件）

一份固件只编入需要的 capability 插件。屏版不带 `arm`；臂版不带 `panel`/`audio`（除非硬件真有）。  
**视觉**不是固件插件，见 [`VISION-PATHWAY.md`](./VISION-PATHWAY.md)（通路 B）。  
**JEV 舵机环**不是固件插件，见 [`JEV-SERVO-PATHWAY.md`](./JEV-SERVO-PATHWAY.md)（通路 C；云只下发目标，不做轨迹密采样）。  
找人/存在检测任务见 [`PRESENCE-FOLLOW-PATHWAY.md`](./PRESENCE-FOLLOW-PATHWAY.md)。  
见 [`PLUGIN-RUNTIME.md`](./PLUGIN-RUNTIME.md)、[`ROARM-PRODUCT.md`](./ROARM-PRODUCT.md)。
