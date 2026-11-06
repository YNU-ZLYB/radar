const HOT_TERMS = [
  '白糖', '郑糖', '食糖', '糖厂', '甘蔗', '原糖', '甜菜',
  '棉花', '郑棉', '籽棉', '皮棉', '新疆棉', '轧花厂', '棉纱',
  '甲醇', '煤制甲醇', 'MTO', '烯烃', '伊朗',
  '纯碱', '光伏玻璃', '浮法玻璃', '重碱', '轻碱', '玻璃', '冷修', '窑炉', '保交楼',
  '原油', '布伦特', 'WTI', '上海原油',
  '减产', '增产', '停产', '复产', '检修', '停车', '限产', '限气',
  '去库', '累库', '上涨', '下跌', '涨价', '降价', '上调', '下调',
  '推迟', '跌破', '累积', '去化', '偏紧', '宽松',
]

const ESCAPED = HOT_TERMS
  .slice()
  .sort((a, b) => b.length - a.length)
  .map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))

const PATTERN = new RegExp(
  `(${ESCAPED.join('|')}|\\d+(?:\\.\\d+)?\\s*(?:%|万吨|万手|元/吨|元/公斤|美元|天|个百分点))`,
  'g'
)

export function highlightParts(text) {
  if (!text) return []
  const parts = []
  let last = 0
  for (const m of text.matchAll(PATTERN)) {
    if (m.index > last) parts.push({ text: text.slice(last, m.index), hot: false })
    parts.push({ text: m[0], hot: true })
    last = m.index + m[0].length
  }
  if (last < text.length) parts.push({ text: text.slice(last), hot: false })
  return parts
}
