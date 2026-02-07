# Maven 构建踩坑总结（2026-02-04）

## 背景
在 red-fluss 的 `fluss-fs-red-s3` 构建过程中，出现多次构建失败和运行时 `s3a` 插件不可用的问题。以下为关键坑点与修复方式，便于后续快速回溯。

## 坑点 1：`maven-shade-plugin` 报 `Invalid signature file digest`
**现象**
- `maven-shade-plugin:shade` 失败，提示 `Invalid signature file digest for Manifest main attributes`。

**原因**
- 参与 shade 的 jar 内部带有签名文件（如 `META-INF/*.SF/DSA/RSA/EC`），shade 过程中会触发签名校验失败。

**修复**
- 在 `maven-jar-plugin` 和 `maven-shade-plugin` 中排除签名文件。

示例（`pom.xml` 片段）
```xml
<excludes>
  <exclude>META-INF/*.SF</exclude>
  <exclude>META-INF/*.DSA</exclude>
  <exclude>META-INF/*.RSA</exclude>
  <exclude>META-INF/*.EC</exclude>
</excludes>
```

## 坑点 2：`dependency:copy-dependencies` 并不会生成插件 jar
**现象**
- 仅执行 `dependency:copy-dependencies` 后，运行仍提示 `UnsupportedFileSystemSchemeException: s3a`。

**原因**
- 该目标只拷贝依赖，不会生成 `fluss-fs-red-s3-0.9-SNAPSHOT.jar`。

**修复**
- 必须执行 `package` 生成插件 jar。

命令：
```bash
./mvnw -pl fluss-filesystems/fluss-fs-red-s3 -am \
  -DskipTests -Dcheckstyle.skip=true -Drat.skip=true -Dspotless.check.skip=true package
```

## 坑点 3：旧 jar 损坏导致 shade/运行失败
**现象**
- `Error creating shaded jar: error in opening zip file`。

**原因**
- `target/fluss-fs-red-s3-0.9-SNAPSHOT.jar` 可能被上一次中断构建写坏。

**修复**
- 构建前清理目标文件和目录：
```bash
rm -f fluss-filesystems/fluss-fs-red-s3/target/fluss-fs-red-s3-0.9-SNAPSHOT.jar
rm -rf fluss-filesystems/fluss-fs-red-s3/target/dependency
rm -rf fluss-filesystems/fluss-fs-red-s3/target/classes
```

## 坑点 4：classpath 断行导致插件 jar 未加载
**现象**
- 即使 jar 已生成，运行时仍报 `UnsupportedFileSystemSchemeException: s3a`。

**原因**
- 启动命令的 `-cp` 被换行截断（尤其是 `fluss-fs-red-s3-0.9-SNAPSHOT.jar` 这一段），导致 jar 实际未进入 classpath。

**修复**
- 使用单行 classpath 或变量拼接，避免断行：
```bash
CP="fluss-client/target/fluss-client-0.9-SNAPSHOT.jar:...:fluss-filesystems/fluss-fs-red-s3/target/fluss-fs-red-s3-0.9-SNAPSHOT.jar"
java -cp "$CP" ...
```

## 坑点 5：SLF4J NOP，导致日志“看起来没打印”
**现象**
- 启动时提示 `Defaulting to no-operation (NOP) logger implementation`。

**原因**
- `log4j-slf4j-impl` 未在 classpath 中（通常遗漏 `fluss-client/target/dependency/*`）。

**修复**
- 确保 classpath 包含 `fluss-client/target/dependency/*`。

## 验证插件是否加载
建议用一个最小 Java 探测类验证 `ServiceLoader` 能发现 `RedS3FileSystemPlugin`：

```java
import java.util.ServiceLoader;
import org.apache.fluss.fs.FileSystemPlugin;

public class CheckFsPlugins {
    public static void main(String[] args) {
        ServiceLoader<FileSystemPlugin> loader = ServiceLoader.load(FileSystemPlugin.class);
        for (FileSystemPlugin plugin : loader) {
            System.out.println("plugin=" + plugin.getClass().getName() + " scheme=" + plugin.getScheme());
        }
    }
}
```

## 备注
- 运行环境使用 Java 17，但系统默认 `javac` 可能仍是 1.8，手动指定 `javac` 17 编译小工具以避免 `class file has wrong version`。

