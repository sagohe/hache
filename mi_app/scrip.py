from datetime import datetime, timedelta, time
from django.db import transaction
from mi_app.models import Asignatura, Aula, NoDisponibilidad, Horario

def generar_horarios():
    asignaturas = Asignatura.objects.all()
    aulas_disponibles = list(Aula.objects.all())

    # Define los rangos de jornada
    JORNADAS = {
        'Mañana': (time(7, 30), time(12, 50)),
        'Tarde': (time(13, 30), time(18, 15)),
        'Noche': (time(18, 15), time(21, 45)),
    }

    with transaction.atomic():
        for asignatura in asignaturas:
            minutos_disponibles = asignatura.intensidad_horaria  # minutos semanales
            docente = asignatura.docentes.first()
            jornada = asignatura.jornada

            if not docente:
                print(f"[ERROR] La asignatura '{asignatura.nombre}' no tiene docente asignado.")
                continue

            hora_jornada_inicio, hora_jornada_fin = JORNADAS.get(jornada, (None, None))
            if not hora_jornada_inicio:
                print(f"[ERROR] Jornada no válida para '{asignatura.nombre}'.")
                continue

            for dia in range(1, 8):  # Asumiendo 1=lunes, 7=domingo
                if minutos_disponibles <= 0:
                    break

                # Obtener bloques de no disponibilidad para ese día
                bloques_no_disponibles = NoDisponibilidad.objects.filter(
                    docente=docente, jornada=jornada, dia=dia
                ).order_by('hora_inicio')

                bloques_libres = []
                actual_inicio = hora_jornada_inicio

                for bloque in bloques_no_disponibles:
                    if actual_inicio < bloque.hora_inicio:
                        bloques_libres.append((actual_inicio, bloque.hora_inicio))
                    actual_inicio = max(actual_inicio, bloque.hora_fin)

                if actual_inicio < hora_jornada_fin:
                    bloques_libres.append((actual_inicio, hora_jornada_fin))

                for inicio, fin in bloques_libres:
                    hora_actual = inicio
                    while minutos_disponibles > 0 and hora_actual < fin:
                        duracion_bloque = min(300, minutos_disponibles)
                        hora_fin = (datetime.combine(datetime.today(), hora_actual) + timedelta(minutes=duracion_bloque)).time()

                        if hora_fin > fin:
                            break

                        aula_disponible = asignatura.aula
                        if not aula_disponible:
                            aula_disponible = next(
                                (a for a in aulas_disponibles if not Horario.objects.filter(
                                    dia=dia,
                                    aula=a,
                                    jornada=jornada,
                                    hora_inicio__lt=hora_fin,
                                    hora_fin__gt=hora_actual
                                ).exists()),
                                None
                            )

                        if not aula_disponible:
                            print(f"No hay aula disponible para {asignatura.nombre} en el día {dia}.")
                            break

                        Horario.objects.create(
                            asignatura=asignatura,
                            docente=docente,
                            aula=aula_disponible,
                            dia=dia,
                            jornada=jornada,
                            hora_inicio=hora_actual,
                            hora_fin=hora_fin
                        )

                        print(f"{asignatura.nombre} asignado a {docente} en {aula_disponible} el día {dia} - {hora_actual} a {hora_fin}")

                        minutos_disponibles -= duracion_bloque
                        hora_actual = hora_fin

    print("Horarios generados y guardados en la base de datos.")