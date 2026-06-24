# External assets and portability

大文件外置策略是通用 harness 的核心部分之一。

## 禁止 hard link

hard link 依赖同一文件系统、inode、设备号和本机挂载语义，不适合跨机器、跨平台、跨文件系统或跨挂载点的长期项目。因此 harness 不把 hard link 当作功能路径。

## symlink 不是 canonical

symlink 可以作为某个本地项目为了兼容旧脚本的 optional convenience，但恢复项目不能依赖 symlink。

## canonical 引用

真正可迁移的引用链是：

```text
run input -> asset_id
asset_id -> .project_os/indexes/asset_locations.tsv
location -> absolute path / storage root / checksum / availability
```

最小信息包括：

- `asset_id`
- logical name / usage
- primary path
- backup / mirror locations
- checksum
- old path mapping
- availability

## 外置动作

`externalize-asset` 应只做：

1. copy 或 move；
2. checksum verify；
3. register asset/location；
4. report old path -> asset_id -> location mapping。

不创建 hardlink。symlink 如未来支持，也必须是单独 opt-in 的本地兼容层。
