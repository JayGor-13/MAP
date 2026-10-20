package local.streaming.catalog;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.aop.framework.ProxyFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.AnnotationTransactionAttributeSource;
import org.springframework.transaction.interceptor.TransactionInterceptor;
import org.springframework.transaction.support.SimpleTransactionStatus;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class StoreProxyTest {
    final JdbcTemplate db = mock(JdbcTemplate.class);
    final PlatformTransactionManager transactions = mock(PlatformTransactionManager.class);

    Store proxiedStore() {
        when(transactions.getTransaction(any())).thenReturn(new SimpleTransactionStatus());
        var factory = new ProxyFactory(new Store(db, new ObjectMapper()));
        factory.setProxyTargetClass(true);
        var advice = new TransactionInterceptor();
        advice.setTransactionManager(transactions);
        advice.setTransactionAttributeSource(new AnnotationTransactionAttributeSource());
        factory.addAdvice(advice);
        return (Store) factory.getProxy();
    }

    @Test void healthBrowseAndRelayReachTheTargetThroughATransactionProxy() {
        var store = proxiedStore();
        when(db.queryForObject("SELECT 1", Integer.class)).thenReturn(1);
        when(db.queryForList(anyString())).thenReturn(List.of(Map.of("id", "event-1")));

        assertEquals(Map.of("status", "ok"), new Health(store).ready());
        assertNotNull(store.browse(Map.of("region", "IN", "maturity", 18), "drama", 20, 0));
        assertEquals("event-1", store.pendingEvents().getFirst().get("id"));
        store.markSent("event-1");

        verify(db).queryForObject("SELECT 1", Integer.class);
        verify(db).update("UPDATE outbox SET sent=true WHERE id=?", "event-1");
    }

    @Test void projectionUsesTheTargetDatabaseAndCommitsItsTransaction() {
        var projection = new Projection(proxiedStore());
        projection.consume("{\"version\":2,\"data\":{\"id\":\"title-1\",\"version\":2}}");

        verify(db).update(startsWith("INSERT INTO titles"), eq("title-1"), eq(2), anyString());
        verify(transactions).commit(any());
    }
}
