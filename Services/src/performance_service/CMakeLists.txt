include_directories(${PROTO_BIN_DIR})

add_executable(performance_service
    main.cpp
    performance_service_impl.cpp
)

target_link_libraries(performance_service
    common
    proto
    ${GRPC_LIBRARIES}
    ${PROTOBUF_LIBRARIES}
    ${MYSQL_LIBRARIES}
    Threads::Threads
)