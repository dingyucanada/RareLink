import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export default function MarkdownReport({ content }: { content: string }) {
  return <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>;
}
