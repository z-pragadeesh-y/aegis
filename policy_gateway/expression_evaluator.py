import ast

ALLOWED_AST_NODES = (
    ast.Expression,
    ast.Attribute,
    ast.Name,
    ast.Constant,
    ast.Compare,
    ast.BoolOp,
    ast.UnaryOp,
    ast.List,
    ast.Tuple,
    ast.Load,
    ast.Eq,
    ast.NotEq,
    ast.In,
    ast.NotIn,
    ast.And,
    ast.Or,
    ast.Not,
)

class ExpressionSecurityError(ValueError):
    """Raised when an expression contains disallowed AST nodes or constructs."""
    pass

def validate_ast(node: ast.AST) -> None:
    """Recursively validate that AST contains only whitelisted node types."""
    if not isinstance(node, ALLOWED_AST_NODES):
        raise ExpressionSecurityError(
            f"Disallowed AST node type '{type(node).__name__}' in condition expression"
        )
    for child in ast.iter_child_nodes(node):
        validate_ast(child)

def _eval_node(node: ast.AST, context: dict):
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, context)
    
    elif isinstance(node, ast.Constant):
        return node.value
    
    elif isinstance(node, ast.Name):
        return context.get(node.id)
    
    elif isinstance(node, ast.Attribute):
        val = _eval_node(node.value, context)
        if isinstance(val, dict):
            return val.get(node.attr)
        elif val is not None:
            return getattr(val, node.attr, None)
        return None
    
    elif isinstance(node, (ast.List, ast.Tuple)):
        return [_eval_node(elt, context) for elt in node.elts]
    
    elif isinstance(node, ast.Compare):
        left_val = _eval_node(node.left, context)
        for op, comp in zip(node.ops, node.comparators):
            right_val = _eval_node(comp, context)
            if isinstance(op, ast.Eq):
                res = (left_val == right_val)
            elif isinstance(op, ast.NotEq):
                res = (left_val != right_val)
            elif isinstance(op, ast.In):
                if right_val is None:
                    res = False
                else:
                    res = (left_val in right_val)
            elif isinstance(op, ast.NotIn):
                if right_val is None:
                    res = True
                else:
                    res = (left_val not in right_val)
            else:
                raise ExpressionSecurityError(f"Unsupported comparison operator: {type(op).__name__}")
            
            if not res:
                return False
            left_val = right_val
        return True
    
    elif isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            for val_node in node.values:
                if not _eval_node(val_node, context):
                    return False
            return True
        elif isinstance(node, ast.Or):
            for val_node in node.values:
                if _eval_node(val_node, context):
                    return True
            return False
        else:
            raise ExpressionSecurityError(f"Unsupported boolean operator: {type(node.op).__name__}")
        
    elif isinstance(node, ast.UnaryOp):
        if isinstance(node.op, ast.Not):
            return not _eval_node(node.operand, context)
        else:
            raise ExpressionSecurityError(f"Unsupported unary operator: {type(node.op).__name__}")
        
    else:
        raise ExpressionSecurityError(f"Unhandled AST node type: {type(node).__name__}")

def evaluate_condition(condition_str: str, context: dict) -> bool:
    """
    Parses, validates, and evaluates a rule condition string against context.
    Raises ExpressionSecurityError if condition contains unwhitelisted AST constructs.
    """
    try:
        tree = ast.parse(condition_str, mode='eval')
    except SyntaxError as e:
        raise ExpressionSecurityError(f"Syntax error in condition '{condition_str}': {e}")
    
    validate_ast(tree)
    return bool(_eval_node(tree, context))
