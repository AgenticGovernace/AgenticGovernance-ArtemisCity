import { Box } from '@chakra-ui/react';
import ReactMarkdown from 'react-markdown';

const getSafeMarkdownHref = (href: string | undefined): string | undefined => {
  if (!href) return undefined;
  const trimmed = href.trim();
  if (!trimmed || trimmed.startsWith('//')) return undefined;

  // Keep same-origin report references and anchors usable without allowing a
  // markdown document to turn a link into a protocol-relative redirect.
  if (
    trimmed.startsWith('#') ||
    trimmed.startsWith('/') ||
    trimmed.startsWith('./') ||
    trimmed.startsWith('../')
  ) {
    return trimmed;
  }

  try {
    const parsed = new URL(trimmed, 'https://artemis.invalid');
    return ['http:', 'https:', 'mailto:', 'tel:'].includes(parsed.protocol)
      ? trimmed
      : undefined;
  } catch {
    return undefined;
  }
};

const ReportMarkdown = ({ content }: { content: string }) => (
  <Box
    p={4}
    borderWidth="1px"
    borderColor="rgba(255,255,255,0.10)"
    borderRadius="lg"
    bg="rgba(0,0,0,0.30)"
    color="#e2e8f0"
    sx={{
      '& h1, & h2, & h3, & h4, & h5, & h6': {
        color: '#f8fafc',
        fontWeight: 600,
        mt: 4,
        mb: 2,
      },
      '& p, & li, & td, & th': { color: '#e2e8f0' },
      '& strong': { color: '#f8fafc' },
      '& a': { color: '#67e8f9', textDecoration: 'underline' },
      '& code': {
        bg: 'rgba(255,255,255,0.06)',
        color: '#fcd34d',
        px: 1.5,
        py: 0.5,
        borderRadius: '4px',
        fontFamily: 'mono',
        fontSize: '0.9em',
      },
      '& pre': {
        bg: 'rgba(0,0,0,0.5)',
        color: '#e2e8f0',
        p: 3,
        borderRadius: '8px',
        overflowX: 'auto',
        border: '1px solid rgba(255,255,255,0.10)',
      },
      '& pre code': { bg: 'transparent', color: 'inherit', p: 0 },
      '& blockquote': {
        borderLeft: '3px solid rgba(34,211,238,0.5)',
        pl: 3,
        color: '#cbd5e1',
        fontStyle: 'italic',
      },
      '& hr': { borderColor: 'rgba(255,255,255,0.10)', my: 4 },
      '& table': { borderCollapse: 'collapse', my: 2 },
      '& th, & td': {
        border: '1px solid rgba(255,255,255,0.10)',
        px: 2,
        py: 1,
      },
      '& ul, & ol': { pl: 5 },
    }}
  >
    <ReactMarkdown
      // Reports are data, not trusted HTML templates. Keep raw HTML disabled
      // explicitly even if the markdown library's default changes later.
      skipHtml
      components={{
        a: ({ node: _node, href, children, target: _target, rel: _rel, ...props }) => {
          void _node;
          void _target;
          void _rel;
          const safeHref = getSafeMarkdownHref(href);
          const external = Boolean(safeHref && /^https?:\/\//i.test(safeHref));
          return (
            <a
              {...props}
              href={safeHref ? safeHref : undefined}
              target={external ? '_blank' : undefined}
              rel={external ? 'noreferrer' : undefined}
            >
              {children}
            </a>
          );
        },
      }}
    >
      {content}
    </ReactMarkdown>
  </Box>
);

export default ReportMarkdown;
