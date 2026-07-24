add_library(common STATIC
    logger.cpp
    config.cpp
    db_connection_pool.cpp
    grpc_client_wrapper.cpp
    utils.cpp
    scene_resolver.cpp
)

target_link_libraries(common
    proto
    ${MYSQL_LIBRARIES}
    ${GRPC_LIBRARIES}
    ${PROTOBUF_LIBRARIES}
    Threads::Threads
)