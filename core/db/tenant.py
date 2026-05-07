from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

_tenant_factories: dict = {}

def get_tenant_session_factory(db_url: str):
    if db_url not in _tenant_factories:
        engine = create_async_engine(db_url, pool_size=3, echo=False)
        _tenant_factories[db_url] = async_sessionmaker(engine, expire_on_commit=False)
    return _tenant_factories[db_url]

async def get_tenant_session(db_url: str) -> AsyncSession:
    factory = get_tenant_session_factory(db_url)
    async with factory() as session:
        yield session
