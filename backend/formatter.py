import re

# ---------------------------------------------------------------------------
# 1. 核心词法定义 (采用 @@ 隔离符，绝对安全)
# ---------------------------------------------------------------------------

COMPOUND_KEYWORDS = {
    'END IF': '@@END_IF@@',
    'END LOOP': '@@END_LOOP@@',
    'END CASE': '@@END_CASE@@',
    'GROUP BY': '@@GROUP_BY@@',
    'ORDER BY': '@@ORDER_BY@@',
    'INSERT INTO': '@@INSERT_INTO@@',
    'DELETE FROM': '@@DELETE_FROM@@',
    'CREATE OR REPLACE': '@@CREATE_OR_REPLACE@@',
    'LEFT JOIN': '@@LEFT_JOIN@@',
    'RIGHT JOIN': '@@RIGHT_JOIN@@',
    'INNER JOIN': '@@INNER_JOIN@@',
    'EXIT WHEN': '@@EXIT_WHEN@@',
}

# 遇到这些关键字，强制在它们【之前】换行
BREAK_BEFORE = {
    'DECLARE', 'BEGIN', 'EXCEPTION', 'END', '@@END_IF@@', '@@END_LOOP@@', '@@END_CASE@@',
    'IF', 'ELSIF', 'ELSE', 'CASE', 'WHEN', 'FOR', 'WHILE', 'LOOP',
    'SELECT', '@@INSERT_INTO@@', 'UPDATE', '@@DELETE_FROM@@', 'MERGE',
    'FROM', 'WHERE', '@@GROUP_BY@@', 'HAVING', '@@ORDER_BY@@',
    'COMMIT', 'ROLLBACK', 'RETURN', 'EXIT', 'CONTINUE', '@@CREATE_OR_REPLACE@@',
    '@@LEFT_JOIN@@', '@@RIGHT_JOIN@@', '@@INNER_JOIN@@',
    '@@EXIT_WHEN@@',
}

# 遇到这些关键字，强制在它们【之后】换行
BREAK_AFTER = {
    ';', 'BEGIN', 'DECLARE', 'EXCEPTION', 'THEN', 'LOOP', 'ELSE',
    'END', '@@END_IF@@', '@@END_LOOP@@', '@@END_CASE@@', 'IS', 'AS'
}


# ---------------------------------------------------------------------------
# 2. 格式化主逻辑
# ---------------------------------------------------------------------------

def format_oracle_sql(sql):
    if not sql or not sql.strip():
        return ""

    # ==========================================
    # 步骤 A：保护所有的字符串和注释
    # ==========================================
    placeholders = {}
    counter = 0

    def replacer(match):
        nonlocal counter
        val = match.group(0)
        if val.startswith('/*'): prefix = '__MLC_'
        elif val.startswith('--'): prefix = '__SLC_'
        elif val.startswith("'"): prefix = '__STR_'
        else: prefix = '__QID_'
        
        ph = f"{prefix}{counter}__"
        placeholders[ph] = val
        counter += 1
        return f" {ph} "

    pattern = r'/\*.*?\*/|--[^\n]*|\'[^\']*\'|"[^"]*"'
    sql_protected = re.sub(pattern, replacer, sql, flags=re.DOTALL)

    # ==========================================
    # 步骤 B：Token 流分割与规范化
    # ==========================================
    sql_protected = re.sub(r'([(),;])', r' \1 ', sql_protected)
    tokens = sql_protected.split()

    for i, t in enumerate(tokens):
        if not t.startswith('__'):
            tokens[i] = t.upper()

    temp_str = " ".join(tokens)
    for k, v in COMPOUND_KEYWORDS.items():
        temp_str = temp_str.replace(k, v)
    tokens = temp_str.split()

    def is_break_before(t):
        return t in BREAK_BEFORE or t.startswith('__SLC_') or t.startswith('__MLC_')

    def is_break_after(t):
        return t in BREAK_AFTER or t.startswith('__SLC_') or t.startswith('__MLC_')

    # ==========================================
    # 步骤 C：按逻辑智能断行（修复标点吸附，并支持 AND/OR 独立成行）
    # ==========================================
    lines = []
    current_line = []
    
    # 跟踪括号深度与 BETWEEN 状态，防止 BETWEEN 中的 AND 被误断行
    paren_depth = 0
    between_paren_depth = -1
    
    for i, t in enumerate(tokens):
        # 1. 更新括号深度
        if t == '(':
            paren_depth += 1
        elif t == ')':
            paren_depth = max(0, paren_depth - 1)

        # 2. 标记 BETWEEN 出现时的括号深度
        if t == 'BETWEEN':
            between_paren_depth = paren_depth

        # 3. 判定当前 Token 是否需要强制在前换行
        should_break_before = False
        if is_break_before(t):
            should_break_before = True
        elif t in ('AND', 'OR'):
            if t == 'AND' and between_paren_depth == paren_depth:
                # 处于同一括号深度的 BETWEEN 结构中，此 AND 为范围连词，保持在同行并重置状态
                between_paren_depth = -1
            else:
                # 普通逻辑连接词，强制换行
                should_break_before = True

        # 4. 执行换行流组合
        if current_line:
            prev = current_line[-1]
            if should_break_before:
                lines.append(current_line)
                current_line = []
            # 如果上一个词需要事后换行，且当前词不是需要吸附的标点符号，则换行
            elif is_break_after(prev) and t not in (';', ',', ')'):
                lines.append(current_line)
                current_line = []
                
        current_line.append(t)
        
    if current_line:
        lines.append(current_line)

    # ==========================================
    # 步骤 D：关键字对栈计算缩进（修复 CASE END 与 ELSE/WHEN）
    # ==========================================
    stack = []
    indented_lines = []

    for line_tokens in lines:
        if not line_tokens: continue
        
        first = line_tokens[0]
        
        # --- 1. 出栈评估 ---
        if first in ('FROM', '@@LEFT_JOIN@@', '@@RIGHT_JOIN@@', '@@INNER_JOIN@@', '@@LEFT_OUTER_JOIN@@', 'WHERE', '@@GROUP_BY@@', 'HAVING', '@@ORDER_BY@@'):
            # 基础缩进逻辑：DML 块内，FROM/JOIN 缩进少一层，与 SELECT 对齐
            indent = max(0, len(stack) - 1) if 'DML' in stack else len(stack)
            
        elif first in ('ELSIF', 'ELSE'):
            while stack and stack[-1] not in ('IF', 'CASE'): stack.pop()
            if stack and stack[-1] == 'CASE':
                indent = len(stack)  # 保持在 CASE 内部
            else:
                indent = max(0, len(stack) - 1)
                
        elif first == 'WHEN':
            while stack and stack[-1] not in ('CASE', 'EXCEPTION'): stack.pop()
            indent = len(stack)
            
        elif first == 'EXCEPTION':
            while stack and stack[-1] not in ('BLOCK', 'BLOCK_DECLARE'): stack.pop()
            indent = max(0, len(stack) - 1)
            
        elif first in ('END', '@@END_IF@@', '@@END_LOOP@@', '@@END_CASE@@'):
            if first == '@@END_IF@@':
                while stack and stack[-1] != 'IF': stack.pop()
                if stack: stack.pop()
            elif first == '@@END_LOOP@@':
                while stack and stack[-1] != 'LOOP': stack.pop()
                if stack: stack.pop()
            elif first == '@@END_CASE@@':
                while stack and stack[-1] != 'CASE': stack.pop()
                if stack: stack.pop()
            elif first == 'END':
                # 智能探源：判断 END 是用来闭合 CASE 还是 BLOCK/EXCEPTION
                for item in reversed(stack):
                    if item == 'CASE':
                        while stack and stack[-1] != 'CASE': stack.pop()
                        if stack: stack.pop()
                        break
                    elif item in ('BLOCK', 'BLOCK_DECLARE', 'EXCEPTION'):
                        while stack and stack[-1] not in ('BLOCK', 'BLOCK_DECLARE', 'EXCEPTION'): stack.pop()
                        if stack: stack.pop()
                        break
            indent = len(stack)
        else:
            indent = len(stack)

        # --- 2. 渲染当前行文本 ---
        def restore_token(tk):
            if tk.startswith('@@') and tk.endswith('@@'):
                return tk.strip('@@').replace('_', ' ')
            return tk

        line_str = " ".join(restore_token(t) for t in line_tokens)
        line_str = re.sub(r'\s+([(),;])', r'\1', line_str) 
        line_str = line_str.replace(',', ', ')
        
        if indented_lines and indented_lines[-1].strip() != "" and first in ('BEGIN', 'EXCEPTION'):
            indented_lines.append("")
            
        indented_lines.append("    " * indent + line_str)

        # --- 3. 压栈处理（支持 WHEN/ELSE 压栈排版） ---
        for t in line_tokens:
            if t in ('DECLARE', 'IS', 'AS'): stack.append('BLOCK_DECLARE')
            elif t == 'BEGIN':
                if stack and stack[-1] == 'BLOCK_DECLARE': stack[-1] = 'BLOCK'
                else: stack.append('BLOCK')
            elif t == 'EXCEPTION':
                if stack and stack[-1] in ('BLOCK', 'BLOCK_DECLARE'): stack[-1] = 'EXCEPTION'
                else: stack.append('EXCEPTION')
            elif t == 'IF': stack.append('IF')
            elif t == 'CASE': stack.append('CASE')
            elif t == 'WHEN': stack.append('WHEN')
            elif t == 'ELSE': stack.append('ELSE')
            elif t == 'LOOP': stack.append('LOOP')
            elif t in ('SELECT', '@@INSERT_INTO@@', 'UPDATE', '@@DELETE_FROM@@', 'MERGE'):
                stack.append('DML')
            elif t == '(': stack.append('PAREN')
            elif t == ')':
                while stack and stack[-1] != 'PAREN': stack.pop()
                if stack: stack.pop() 
            elif t == ';':
                while stack and stack[-1] == 'DML': stack.pop()

    # ==========================================
    # 步骤 E：注释与字符串完美复原
    # ==========================================
    final_output = []
    for line in indented_lines:
        for ph, val in placeholders.items():
            if ph in line:
                if ph.startswith('__MLC_'):
                    indent_spaces = len(line) - len(line.lstrip())
                    prefix = " " * indent_spaces
                    val_lines = val.split('\n')
                    val = '\n'.join([val_lines[0]] + [prefix + ' ' + vl.strip() if vl.strip() else prefix for vl in val_lines[1:]])
                line = line.replace(ph, val)
        final_output.append(line)

    return "\n".join(final_output)