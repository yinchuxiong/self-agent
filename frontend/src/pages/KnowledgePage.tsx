import { DatabaseOutlined } from "@ant-design/icons";
import { Empty, Table, Typography } from "antd";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import PageHeader from "../components/PageHeader";

export default function KnowledgePage() {
  const [documents, setDocuments] = useState<Record<string, unknown>[]>([]);

  useEffect(() => {
    void api.documents().then(setDocuments);
  }, []);

  return (
    <div className="pageGrid">
      <PageHeader title="知识库" subtitle="文档上传、分片、入库和检索测试的预留入口" />
      {documents.length === 0 ? (
        <div className="emptyPanel">
          <DatabaseOutlined />
          <Typography.Title level={4}>还没有文档</Typography.Title>
          <Typography.Text>下一阶段会接入 DocumentLoader、Splitter 和 Qdrant。</Typography.Text>
        </div>
      ) : (
        <Table rowKey="id" dataSource={documents} />
      )}
    </div>
  );
}

