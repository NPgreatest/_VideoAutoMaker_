#!/usr/bin/env python3
import json
import os

def main():
    project = input("请输入项目名 (例如 mh370_demo): ").strip()
    script = []
    line_num = 1

    print("\n开始输入剧本文本，每行一条。输入 --end 结束。\n")

    while True:
        line = input(f"L{line_num}> ").strip()
        if line == "--end":
            break
        if not line:
            continue
        script.append({
            "id": f"L{line_num}",
            "text": line
        })
        line_num += 1

    data = {
        "project": project,
        "script": script
    }

    # 构造保存路径
    save_dir = os.path.join("project", project)
    os.makedirs(save_dir, exist_ok=True)
    out_path = os.path.join(save_dir, f"{project}.json")

    # 保存 JSON 文件
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 已生成 JSON 文件: {out_path}")
    print(json.dumps(data, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
