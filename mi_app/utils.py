from datetime import datetime, timedelta, time
from .models import NoDisponibilidad, Horario, Asignatura
from django.core.exceptions import ValidationError


def obtener_bloques_por_jornada(jornada):
    bloques = {
        'Mañana': [time(7, 30), time(9, 30), time(10, 30)],
        'Tarde': [time(13, 30), time(15, 30), time(16, 30)],
        'Noche': [time(18, 30), time(19, 30)],
    }
    return bloques.get(jornada, [])

def esta_disponible(docente, jornada, dia, hora_inicio, hora_fin):
    return not NoDisponibilidad.objects.filter(
        docente=docente,
        jornada=jornada,
        dia=dia,
        hora_inicio__lt=hora_fin,
        hora_fin__gt=hora_inicio
    ).exists()

def aula_disponible(aula, dia, hora_inicio, hora_fin):
    return not Horario.objects.filter(
        aula=aula,
        dia=dia,
        hora_inicio__lt=hora_fin,
        hora_fin__gt=hora_inicio
    ).exists()

def docente_disponible(docente, dia, hora_inicio, hora_fin):
    return not Horario.objects.filter(
        docente=docente,
        dia=dia,
        hora_inicio__lt=hora_fin,
        hora_fin__gt=hora_inicio
    ).exists()

def hay_conflicto_estudiantes(asignatura, dia, hora_inicio, hora_fin):
    return not Horario.objects.filter(
        asignatura__semestre=asignatura.semestre,
        asignatura__semestre__carrera=asignatura.semestre.carrera,
        jornada=asignatura.jornada,
        dia=dia,
        hora_inicio__lt=hora_fin,
        hora_fin__gt=hora_inicio
    ).exclude(
        asignatura=asignatura
    ).exists()

def puede_asignar_horario(docente, aula, asignatura, dia, jornada, hora_inicio, hora_fin):
    return (
        esta_disponible(docente, jornada, dia, hora_inicio, hora_fin) and
        aula_disponible(aula, dia, hora_inicio, hora_fin) and
        docente_disponible(docente, dia, hora_inicio, hora_fin) and
        hay_conflicto_estudiantes(asignatura, dia, hora_inicio, hora_fin) and
        not Horario.objects.filter(asignatura=asignatura, dia=dia).exists()
    )

def obtener_dias_disponibles_carrera(carrera):
    """
    Retorna una lista de nombres de días disponibles para la carrera.
    """
    return list(carrera.dias_clase.values_list('nombre', flat=True))

def asignar_horario_automatico(asignatura):
    jornada = asignatura.jornada
    semestre = asignatura.semestre

    if not semestre:
        return False

    carrera = semestre.carrera
    dias_validos = list(carrera.dias_clase.values_list('nombre', flat=True))
    intensidad = asignatura.intensidad_horaria

    bloques_por_jornada = {
        'Mañana': [('07:30', '09:30'), ('09:30', '10:30'), ('10:30', '12:30')],
        'Tarde': [('13:30', '15:30'), ('15:30', '16:30'), ('16:30', '18:15')],
        'Noche': [('18:15', '19:30'), ('19:30', '21:00'), ('21:00', '21:45')],
    }

    bloques = [
        (
            datetime.strptime(inicio, "%H:%M").time(),
            datetime.strptime(fin, "%H:%M").time()
        ) for inicio, fin in bloques_por_jornada.get(jornada, [])
    ]

    docente = asignatura.docentes.first()
    aula = asignatura.aula

    if not docente or not aula:
        return False

    for dia in dias_validos:
        for i in range(len(bloques)):
            duracion_acumulada = 0
            bloques_usados = []

            for j in range(i, len(bloques)):
                hi, hf = bloques[j]
                duracion = (
                    datetime.combine(datetime.today(), hf) -
                    datetime.combine(datetime.today(), hi)
                ).seconds // 60

                bloques_usados.append((hi, hf))
                duracion_acumulada += duracion

                if duracion_acumulada >= intensidad:
                    hi_total = bloques_usados[0][0]
                    hf_total = bloques_usados[-1][1]

                    conflictos_docente = Horario.objects.filter(
                        docente=docente,
                        dia=dia,
                        hora_inicio__lt=hf_total,
                        hora_fin__gt=hi_total
                    ).exists() 
                    
                    conflicto_disponibilidad = NoDisponibilidad.objects.filter(
                        docente=docente,
                        dia=dia,
                        jornada=jornada,
                        hora_inicio__lt=hf_total,
                        hora_fin__gt=hi_total
                    ).exists()

                    conflictos_aula = Horario.objects.filter(
                        aula=aula,
                        dia=dia,
                        hora_inicio__lt=hf_total,
                        hora_fin__gt=hi_total
                    ).exists()

                    conflictos_estudiantes = hay_conflicto_estudiantes(asignatura, dia, hi_total, hf_total)

                    if not (conflictos_docente or conflictos_aula or conflictos_estudiantes or conflicto_disponibilidad):
                        Horario.objects.create(
                            asignatura=asignatura,
                            docente=docente,
                            aula=aula,
                            dia=dia,
                            jornada=jornada,
                            hora_inicio=hi_total,
                            hora_fin=hf_total
                        )
                        return True
                    # Si hay conflicto, continúa probando otros bloques del mismo día
        # Si termina todos los bloques del día sin éxito, pasa al siguiente día
    return False
#Horarios generados