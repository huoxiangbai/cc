"""Parse generated SQL, resolve configured model relations, retain chart metadata."""
import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import traverse_scope

DIALECTS={'mysql':'mysql','clickhouse':'clickhouse','h2':'mysql','sqlite':'sqlite'}


def render(tree,dialect):
    if dialect!='sqlite':return tree.sql(dialect=DIALECTS[dialect])
    from sqlglot.dialects.sqlite import SQLite
    class Generator(SQLite.Generator):
        def tablealias_sql(self,expression):
            if isinstance(expression.parent,exp.CTE) and expression.args.get('columns'):
                return self.sql(expression,'this')+'('+self.expressions(expression,key='columns',flat=True)+')'
            return super().tablealias_sql(expression)
    return Generator(dialect='sqlite').generate(tree)


def select_sql(sql,dialect):
    if dialect not in DIALECTS:raise ValueError('Unsupported business DB dialect')
    statements=sqlglot.parse(sql,read=DIALECTS[dialect])
    if len(statements)!=1 or not isinstance(statements[0],(exp.Select,exp.Union)):raise ValueError('Expected a single SELECT query')
    tree=statements[0]
    if any(s.args.get('into') or s.args.get('locks') for s in tree.find_all(exp.Select)):raise ValueError('SELECT INTO/locks are not query results')
    return tree


def resolve(sql,models,dialect):
    tree=select_sql(sql,dialect)
    relations=[source for scope in traverse_scope(tree) for source in scope.sources.values() if isinstance(source,exp.Table)]
    modelmap={m['modelCode']:m for m in models}
    if not relations:raise ValueError('SQL has no model relation')
    used=[]
    for table in relations:
        model=modelmap.get(table.name)
        if not model or table.db or table.catalog:raise ValueError('Unknown modelCode: '+table.name)
        used.append(model)
    columns=[];schemas={s['columnId'].lower():s for m in used for s in m.get('schemaList') or []}
    selection=tree
    while isinstance(selection,exp.Union):selection=selection.expression
    projections=selection.expressions
    star=len(projections)==1 and (isinstance(projections[0],exp.Star) or isinstance(projections[0],exp.Column) and projections[0].is_star)
    if star:
        # Original columnMap is a Java HashMap: keep its stable bucket iteration order.
        capacity=16
        while len(schemas)>capacity*.75:capacity*=2
        def bucket(key):
            h=0
            for ch in key:h=(31*h+ord(ch))&0xffffffff
            return (h^(h>>16))&(capacity-1)
        projections=[exp.column(s['columnId']) for _,s in sorted(schemas.items(),key=lambda kv:bucket(kv[0]))]
    order={o.this.alias_or_name.lower():('DESC' if o.args.get('desc') else 'ASC') for o in (tree.args.get('order') or exp.Order()).expressions}
    for projection in projections:
        expression=projection.this if isinstance(projection,exp.Alias) else projection
        column=next(expression.find_all(exp.Column),None)
        info=schemas.get(column.name.lower(),{}) if column else {}
        agg=next(expression.find_all(exp.AggFunc),None)
        identifier=isinstance(expression,exp.Column)
        # Calcite's original parser classifies aggregate/arithmetic metadata only
        # in its explicit AS branch. Keep that observable DTO behavior.
        classified=isinstance(projection,exp.Alias)
        dtype=info.get('dataType') if identifier else 'DECIMAL' if classified and (agg or isinstance(expression,(exp.Add,exp.Sub,exp.Mul,exp.Div))) else None
        display=expression.copy()
        for item in display.find_all(exp.Column):item.this.set('quoted',True)
        guid=(projection.alias if classified else expression.name if identifier else display.sql(dialect=DIALECTS[dialect])).lower()
        kind='IDENTIFIER' if identifier else 'OTHER_FUNCTION' if isinstance(expression,exp.Func) else {'add':'PLUS','sub':'MINUS','mul':'TIMES','div':'DIVIDE'}.get(expression.key,expression.key.upper())
        columns.append({'col':'.'.join(part.name for part in expression.parts) if identifier else display.sql(dialect=DIALECTS[dialect]),'agg':agg.key.upper() if agg and classified else None,'order':order.get(guid),
            'guid':guid,'name':(info.get('columnName') if identifier else projection.alias) or guid,'dataType':None if star else dtype,'colType':info.get('dataType') if star else kind})
        if dialect=='sqlite' and not identifier and not classified:
            # Align real SQLite cursor labels with the existing column GUID.
            projection.replace(exp.alias_(projection.copy(),guid,quoted=True))
    filters=parse_filters(selection.args.get('where'),schemas)
    for table,model in zip(relations,used):
        if model['type'].lower()=='table':
            replacement=sqlglot.parse_one('SELECT * FROM '+model['content'],read=DIALECTS[dialect]).args['from'].this
            if not isinstance(replacement,exp.Table):raise ValueError('Invalid table model')
            replacement.set('alias',table.args.get('alias'))
        elif model['type'].lower()=='sql':
            sub=select_sql(model['content'],dialect)
            replacement=exp.Subquery(this=sub,alias=table.args.get('alias') or exp.TableAlias(this=exp.to_identifier(table.name)))
        else:raise ValueError('Unsupported model type')
        table.replace(replacement)
    measures=[c['guid'] for c in columns if c['agg'] or (c['dataType'] or '').upper()=='DECIMAL']
    return render(tree,dialect),columns,filters,[c['guid'] for c in columns if c['guid'] not in measures],measures


def parse_filters(where,schemas):
    names={'eq':('EQUALS','等于'),'neq':('NOT_EQUALS','不等于'),'gt':('GREATER_THAN','大于'),'gte':('GREATER_THAN_OR_EQUAL','大于等于'),'lt':('LESS_THAN','小于'),'lte':('LESS_THAN_OR_EQUAL','小于等于'),'like':('LIKE','模糊匹配'),'in':('IN','包含'),'between':('BETWEEN','区间')}
    def one(node):
        if isinstance(node,exp.Paren):return one(node.this)
        if isinstance(node,exp.And):return one(node.left)+one(node.right)
        if isinstance(node,exp.Or):return [{'col':None,'opt':None,'optName':None,'val':None,'name':None,'dataType':None,'operator':'OR','subFilters':one(node.left)+one(node.right)}]
        col=next(node.find_all(exp.Column),None)
        if not col:return []
        vals=[v.this for v in node.find_all(exp.Literal)]
        opt,label=names.get(node.key,(node.key.upper(),node.key.upper()))
        return [{'col':col.name,'opt':opt,'optName':label,'val':','.join(str(v) for v in vals) if vals else None,'name':schemas.get(col.name.lower(),{}).get('columnName') or col.name,'dataType':None,'operator':None,'subFilters':None}]
    return one(where.this) if where else []
