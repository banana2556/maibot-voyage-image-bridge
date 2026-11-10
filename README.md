# MaiBot Voyage 圖片嵌入轉接

獨立 MaiBot 插件，在插件 Runner 的 `127.0.0.1:18765` 提供 OpenAI-compatible `/v1/embeddings`。將圖片 Data URI 轉成 Voyage 官方 `/v1/multimodalembeddings` 格式，再轉回 MaiBot 預期的 embedding 回應。**不修改 MaiBot 核心，不提供公開服務，不保存金鑰或圖片。**

## 安裝

將此目錄複製至 MaiBot 的 `plugins/` 並重啟 MaiBot。MaiBot 容器內必須已有 `aiohttp` 和 `maibot-plugin-sdk>=2.21.0`。確認日誌顯示「Voyage 圖片嵌入轉接器已…啟動」。Docker 部署時 Provider URL **必須是 MaiBot 容器內的** `http://127.0.0.1:18765/v1`；不要使用主機的 localhost，也不要對外映射此埠。插件設定可更改監聽埠，更改後需重啟 Runner。

在 MaiBot 的 `model_config.toml` 設定一個獨立的 OpenAI-compatible Provider，base URL 指向 `http://127.0.0.1:18765/v1`，API key 填入**自己的 Voyage API key**（金鑰仍經 MaiBot Provider 設定傳給本機轉接器；絕不提交到插件目錄）。再把 `[[models]]` 的 `model_type` 設為 `image_embedding`、`model_identifier` 設為可用的 `voyage-multimodal-*`、`api_provider` 指向上面新增的 Provider，並在該模型緊接的 `[models.extra_params]` 下設定：

```toml
image_embedding_input = { image = "{data_uri}" }
```

再把 `[model_task_config.image_embedding]` 的 `model_list` 指向該模型；啟用 MaiBot 圖片記憶功能。若目前同一個 Voyage Provider 也用於文字 embedding，請為圖片**新增獨立 Provider**，勿把共用 base URL 改成 localhost。切換圖片嵌入模型／協定可能觸發向量索引重建，請先備份資料。

### 注意

- 只支援 Voyage 官方 `voyage-multimodal-*` 模型；圖片需為 PNG/JPEG/WebP/GIF 的 base64 Data URI，大小上限 15 MB。
- API key 由本機請求的 Bearer header 傳至 Voyage 官方 HTTPS；錯誤回應不轉送上游內文以避免洩露憑證。若你的網路需要 HTTP 代理，本插件預設不信任環境代理變數。
- 這是相容端點而非原生協定註冊：MaiBot 的協定指紋可能與原生內建修補不同。遷移原有索引前備份，讓 MaiBot 正常重建，不能直接視為同一向量空間。
- 如果 MaiBot 版本已內建 Voyage 原生圖片嵌入，應直接使用內建功能，不需此插件。
