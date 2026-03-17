"""Test store operations."""
import pytest

from snowden.store import Store


class TestStoreInit:
    def test_not_connected_by_default(self):
        store = Store()
        assert store._pool is None

    @pytest.mark.asyncio
    async def test_raises_without_connect(self):
        store = Store()
        with pytest.raises(RuntimeError, match="not connected"):
            await store.get_daily_trades()

    @pytest.mark.asyncio
    async def test_close_without_connect(self):
        store = Store()
        await store.close()  # Should not raise
