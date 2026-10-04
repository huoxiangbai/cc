import java.util.*;
import java.lang.reflect.*;
import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.serializer.SerializerFeature;
import org.wwz.ai.domain.agent.rag.Nl2SqlQueryService;
import org.wwz.ai.domain.agent.reactor.data.dto.ChatSchemaDto;
import org.wwz.ai.domain.agent.reactor.data.model.SqlModel;
import org.wwz.ai.domain.agent.reactor.data.sql.SqlParserUtils;
public class SqlP3 {
 public static void main(String[] args) throws Exception {
  var service=new Nl2SqlQueryService(null,null,null,null);
  var schema=new HashMap<String,ChatSchemaDto>();
  for(var key:List.of("category","amount")) {
   var c=new ChatSchemaDto();c.setColumnId(key);c.setColumnName(key.equals("category")?"分类":"金额");c.setDataType(key.equals("category")?"STRING":"DECIMAL");schema.put(key,c);
  }
  var cols=Nl2SqlQueryService.class.getDeclaredMethod("parseColumns",SqlModel.class,Map.class);cols.setAccessible(true);
  var filters=Nl2SqlQueryService.class.getDeclaredMethod("parseFilters",SqlModel.class,Map.class);filters.setAccessible(true);
  var result=new ArrayList<Object>();
  for(var sql:args) {
   var model=SqlParserUtils.parseSelectSql(sql,"mysql");
   var entry=new LinkedHashMap<String,Object>();entry.put("sql",sql);entry.put("columns",cols.invoke(service,model,schema));entry.put("filters",filters.invoke(service,model,schema));result.add(entry);
  }
  System.out.println("P3_SQL_JSON:"+JSON.toJSONString(result,SerializerFeature.WriteMapNullValue));
 }
}
