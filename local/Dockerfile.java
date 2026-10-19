FROM eclipse-temurin:17-jdk AS build
WORKDIR /app
ARG SERVICE
COPY app/msa/${SERVICE}/ ./
RUN chmod +x gradlew && ./gradlew --no-daemon --max-workers=2 bootJar -x test
FROM eclipse-temurin:17-jre
WORKDIR /app
COPY --from=build /app/build/libs/*SNAPSHOT.jar app.jar
ENTRYPOINT ["java", "-jar", "app.jar"]
