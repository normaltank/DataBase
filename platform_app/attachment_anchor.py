"""Fixed file identity and bounded extraction checks; never authenticity claims."""
import hashlib

from .attachment_search import AttachmentIndex, original_path, VERSION


def capture(db, data_dir, attachment, quote, locator, occurrence=0):
    anchor = {key: attachment[key] for key in ['id', 'name', 'bytes', 'sha256']}
    anchor.update(locator=locator, quote=quote, context_prefix='', context_suffix='',
                  normalization='whitespace-v1', extractor_version=VERSION)
    result = {'status': 'unchecked', 'reason': 'unindexed'}
    path = original_path(data_dir, attachment)
    if path is None:
        result['reason'] = 'missing'
    else:
        digest = hashlib.sha256()
        size = 0
        try:
            with path.open('rb') as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b''):
                    size += len(chunk)
                    digest.update(chunk)
        except OSError:
            anchor['quote_match'] = {'status': 'unchecked', 'reason': 'missing'}
            return anchor
        if size != attachment['bytes'] or digest.hexdigest() != attachment['sha256']:
            result['reason'] = 'file_mismatch'
        else:
            indexed = AttachmentIndex(db, data_dir).read(attachment)
            result['reason'] = indexed['status']
            if indexed['status'] == 'ready':
                segments = [s for s in indexed['segments'] if s['locator'] == locator]
                result = {'status': 'not_matched', 'reason': 'quote_not_at_location' if segments else 'location_not_found'}
                normalized = ' '.join(quote.split())
                for segment in segments:
                    text = ' '.join(segment['text'].split())
                    start = text.find(normalized)
                    for _ in range(occurrence):
                        if start < 0:
                            break
                        start = text.find(normalized, start + len(normalized))
                    if normalized and start >= 0:
                        anchor['occurrence'] = occurrence
                        anchor['context_prefix'] = text[max(0, start - 160):start]
                        anchor['context_suffix'] = text[start + len(normalized):start + len(normalized) + 160]
                        result = {'status': 'matched', 'reason': 'at_location'}
                        break
    anchor['quote_match'] = result
    return anchor


def description(anchor):
    if not anchor:
        return '历史未记录附件锚点，无法自动检查当时的文件与位置。'
    result = anchor.get('quote_match') or {}
    labels = {'matched': '已在指定位置的提取文字中匹配', 'not_matched': '未在指定位置的提取文字中匹配',
              'unchecked': '无法检查指定位置的提取文字'}
    reasons = {'at_location': '规范化空白后匹配', 'quote_not_at_location': '该位置未找到相同原句（跨段等情况可手工核对）',
               'location_not_found': '索引未记录该位置（跨段等情况可手工核对）', 'unindexed': '尚无有效索引',
               'empty': '无可提取文字', 'unsupported': '格式不支持', 'limit': '超过提取限制',
               'failed': '提取失败', 'missing': '文件缺失', 'file_mismatch': '文件字节与登记摘要不一致'}
    lines = [labels.get(result.get('status'), labels['unchecked']) + ' · ' + reasons.get(result.get('reason'), '原因未记录')]
    for key, label in [('name', '附件'), ('id', '附件编号'), ('bytes', '字节数'), ('sha256', 'SHA-256'), ('locator', '固定位置'),
                       ('context_prefix', '前文'), ('context_suffix', '后文')]:
        lines.append(label + '：' + str(anchor.get(key) if anchor.get(key) not in (None, '') else '未取得'))
    lines.append('提取文字匹配与文件摘要只供核对，不证明材料真实、身份或研究结论。')
    return '\n'.join(lines)
