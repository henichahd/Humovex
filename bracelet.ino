#include <Wire.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>

Adafruit_MPU6050 mpu;
#define I2C_SDA 25
#define I2C_SCL 26

float yaw = 0; 
unsigned long tempsPrecedent = 0;

void setup() {
  Serial.begin(115200);
  Wire.begin(I2C_SDA, I2C_SCL);

  if (!mpu.begin()) {
    Serial.println("Erreur MPU6050");
    while (1) { delay(10); }
  }
  mpu.setAccelerometerRange(MPU6050_RANGE_4_G);
  mpu.setGyroRange(MPU6050_RANGE_500_DEG);
  mpu.setFilterBandwidth(MPU6050_BAND_94_HZ); // Bande passante élargie pour capter les vibrations
  
  tempsPrecedent = millis();
}

void loop() {
  sensors_event_t a, g, temp;
  mpu.getEvent(&a, &g, &temp);

  unsigned long tempsActuel = millis();
  float dt = (tempsActuel - tempsPrecedent) / 1000.0;
  tempsPrecedent = tempsActuel;

  // 1. Angles (Pitch, Roll, Yaw)
  float pitch = atan2(a.acceleration.x, sqrt(a.acceleration.y * a.acceleration.y + a.acceleration.z * a.acceleration.z)) * 180.0 / PI;
  float roll = atan2(a.acceleration.y, a.acceleration.z) * 180.0 / PI;

  if (abs(g.gyro.z) > 0.05) { 
    yaw += (g.gyro.z * 180.0 / PI) * dt; 
  }

  // 2. Calcul de l'intensité de vibration (en m/s²)
  // Magnitude totale des 3 axes moins la gravité terrestre (9.81)
  float accelTotale = sqrt(pow(a.acceleration.x, 2) + pow(a.acceleration.y, 2) + pow(a.acceleration.z, 2));
  float vibration = abs(accelTotale - 9.81);
  if (vibration < 0.3) vibration = 0.0; // Ignore le bruit de fond au repos

  // 3. Envoi des 4 valeurs en JSON
  Serial.print("{\"pitch\":"); Serial.print(pitch);
  Serial.print(",\"roll\":"); Serial.print(roll);
  Serial.print(",\"yaw\":"); Serial.print(yaw);
  Serial.print(",\"vib\":"); Serial.print(vibration);
  Serial.println("}");
  
  delay(50); 
}